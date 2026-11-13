"""Extract raw product data from Morrisons grocery pages."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from scrapers.etl_contracts import ExtractionResult
from scrapers.logger_setup import logger

BASE_URL = "https://groceries.morrisons.com"
EXCLUDED_CATEGORY_SLUGS = {
    "drinks",
    "baby-toddler",
    "events-inspiration-ways-to-save",
    "health-wellbeing-medicines",
    "home-garden",
    "household",
    "kiosk",
    "new",
    "pet-shop",
    "toiletries-beauty",
    "toys-clothing-entertainment",
    "beer-wines-spirits",
}
EXTRACTION_PROGRESS_INTERVAL = 25
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": f"{BASE_URL}/",
}


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _category_links(soup: BeautifulSoup) -> tuple[set[str], dict[str, str]]:
    urls = set()
    root_names = {}
    for anchor in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, anchor["href"])
        parsed = urlsplit(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "categories":
            continue
        root_slug = parts[1]
        if root_slug in EXCLUDED_CATEGORY_SLUGS:
            continue
        urls.add(_canonical_url(url))
        if len(parts) == 3:
            name = anchor.get_text(" ", strip=True)
            if name:
                root_names.setdefault(root_slug, name)
    return urls, root_names


def _category_name(slug: str, root_names: Mapping[str, str]) -> str:
    if slug in root_names:
        return root_names[slug]
    if slug == "meat-fish":
        return "Meat & Fish"
    return slug.replace("-", " ").title()


def _navigate(page, url: str, attempts: int = 3) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            logger.debug(
                "Navigating to %s (attempt %d/%d).", url, attempt, attempts
            )
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            return True
        except PlaywrightError as error:
            if attempt == attempts:
                logger.warning(
                    "Skipping %s after navigation error: %s", url, error)
                return False
    return False


def _crawl_product_categories() -> dict[str, str]:
    product_categories = {}
    logger.debug("Starting product category discovery.")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=REQUEST_HEADERS["User-Agent"])
            if not _navigate(page, f"{BASE_URL}/categories"):
                return product_categories

            page.locator(
                'a[href*="/categories/"]').first.wait_for(timeout=20000)
            category_urls, root_names = _category_links(
                BeautifulSoup(page.content(), "html.parser")
            )
            logger.debug(
                "Found %d product categories to crawl.", len(category_urls)
            )
            sorted_category_urls = sorted(category_urls)
            for category_index, category_url in enumerate(
                sorted_category_urls, start=1
            ):
                logger.debug(
                    "Crawling product category %d/%d: %s.",
                    category_index,
                    len(sorted_category_urls),
                    category_url,
                )
                if not _navigate(page, category_url):
                    continue
                page.wait_for_timeout(750)

                previous_height = -1
                unchanged_scrolls = 0
                for _ in range(20):
                    page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(500)
                    current_height = page.evaluate(
                        "document.body.scrollHeight")
                    if current_height == previous_height:
                        unchanged_scrolls += 1
                        if unchanged_scrolls >= 2:
                            break
                    else:
                        unchanged_scrolls = 0
                        previous_height = current_height

                parts = urlsplit(category_url).path.strip("/").split("/")
                category_name = _category_name(parts[1], root_names)
                for link in page.locator('a[href*="/products/"]').evaluate_all(
                    "anchors => anchors.map(anchor => anchor.href)"
                ):
                    product_url = _canonical_url(link)
                    product_categories.setdefault(product_url, category_name)
                logger.debug(
                    "Category %d/%d complete; %d product URLs discovered so "
                    "far.",
                    category_index,
                    len(sorted_category_urls),
                    len(product_categories),
                )
        finally:
            browser.close()
    return product_categories


def _walk_json(value: object):
    if isinstance(value, dict):
        yield value
        for nested_value in value.values():
            yield from _walk_json(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            yield from _walk_json(nested_value)


def _product_schema(soup: BeautifulSoup) -> dict[str, object]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk_json(data):
            node_type = node.get("@type", [])
            if isinstance(node_type, str):
                node_type = [node_type]
            if any(str(value).endswith("Product") for value in node_type):
                return node
    return {}


def _first_value(*values: object) -> str | None:
    for value in values:
        if isinstance(value, dict):
            value = value.get("name") or value.get("value")
        if isinstance(value, list):
            value = next((item for item in value if item), None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _serving_unit(header: str) -> str | None:
    match = re.search(
        r"\b(?:per\s+(?:average\s+)?|each\s+)([a-z][a-z-]*)\b",
        header,
        re.I,
    )
    if not match or match.group(1).lower() in {
        "item", "serving", "portion"
    }:
        return None
    return match.group(1).lower()


def _nutrition_table(
    soup: BeautifulSoup,
    product_name: str | None = None,
    prefer_per_item: bool = False,
) -> tuple[dict[str, str], str | None]:
    tables = soup.find_all("table", class_=re.compile("nutrition", re.I))
    table = tables[0] if tables else None
    if product_name and len(tables) > 1:
        normalized_name = re.sub(r"[^a-z0-9]+", " ", product_name.lower())
        for candidate in tables:
            component_label = None
            for sibling in candidate.previous_siblings:
                if getattr(sibling, "name", None) == "table":
                    break
                label = (
                    sibling.get_text(" ", strip=True)
                    if hasattr(sibling, "get_text")
                    else str(sibling).strip()
                )
                if label:
                    component_label = label
                    break
            normalized_label = re.sub(
                r"[^a-z0-9]+", " ", component_label.lower()
            ).strip() if component_label else ""
            if normalized_label and re.search(
                rf"(?:^|\s){re.escape(normalized_label)}(?:\s|$)",
                normalized_name,
            ):
                table = candidate
                break
    labels = {
        "energy_kcal": ("energy",),
        "protein_g": ("protein",),
        "carbohydrates_g": ("carbohydrate",),
        "sugars_g": ("of which sugars", "sugars", "sugar"),
        "saturates_g": (
            "of which saturates", "saturates", "saturated fat"
        ),
        "fat_g": ("fat",),
        "fibre_g": ("fibre", "fiber"),
        "salt_g": ("salt",),
    }

    serving_size_g = None
    serving_unit = None
    counted_item_header_index = None
    if table:
        header_row = table.find("tr")
        headers = header_row.find_all(["th", "td"]) if header_row else []
        header_texts = [
            cell.get_text(" ", strip=True).lower() for cell in headers
        ]
        if product_name:
            for index, value in enumerate(header_texts):
                candidate_unit = _serving_unit(value)
                if candidate_unit and re.search(
                    rf"\b\d+(?:[.,]\d+)?\b(?:\s+[a-z-]+)*\s+"
                    rf"{re.escape(candidate_unit)}s?\b",
                    product_name,
                    re.I,
                ):
                    serving_unit = candidate_unit
                    counted_item_header_index = index
                    break
        for value in header_texts:
            if not re.search(
                r"\beach\b|\bper\s+(?:item|serving|portion)\b|"
                r"\bper\s+\d+\s*/\s*\d+|"
                r"\bper\s+(?:average\s+)?[a-z][a-z-]*\b",
                value,
            ):
                continue
            serving_match = re.search(
                r"\((\d+(?:[.,]\d+)?)\s*g\)", value
            )
            if serving_match:
                serving_size_g = serving_match.group(1).replace(",", ".")
                break
        basis_index = counted_item_header_index
        if basis_index is None and prefer_per_item and serving_size_g is None:
            basis_index = next(
                (
                    index for index, value in enumerate(header_texts)
                    if re.search(
                        r"\beach\b|\bper\s+(?:item|serving|portion)\b",
                        value,
                    ) or _serving_unit(value)
                ),
                None,
            )
        if basis_index is None:
            basis_index = next(
                (
                    index for index, value in enumerate(header_texts)
                    if re.search(r"100\s*g", value)
                ),
                None,
            )
        if basis_index is None:
            basis_index = next(
                (
                    index for index, value in enumerate(header_texts)
                    if re.search(r"100\s*ml", value)
                ),
                None,
            )
        if basis_index is None:
            basis_index = next(
                (
                    index for index, value in enumerate(header_texts)
                    if re.search(r"per\s+(?:item|serving|portion)", value)
                ),
                1 if len(headers) > 1 else 0,
            )
        basis_text = (
            header_texts[basis_index]
            if header_texts
            else table.get_text(" ", strip=True).lower()
        )
        table_rows = [
            row.find_all(["th", "td"]) for row in table.find_all("tr")
        ]
        unit_index = next(
            (index for index, value in enumerate(header_texts)
             if value == "unit"),
            None,
        )
        rows = []
        for row_index, columns in enumerate(table_rows[1:], start=1):
            if len(columns) <= basis_index:
                continue
            label = columns[0].get_text(" ", strip=True).lower()
            value = columns[basis_index].get_text(" ", strip=True)
            if label.startswith("energy") and unit_index is not None:
                unit = (
                    columns[unit_index].get_text(" ", strip=True).lower()
                    if unit_index < len(columns)
                    else ""
                )
                next_columns = (
                    table_rows[row_index + 1]
                    if row_index + 1 < len(table_rows)
                    else []
                )
                next_label = (
                    next_columns[0].get_text(" ", strip=True)
                    if next_columns
                    else ""
                )
                next_unit = (
                    next_columns[unit_index].get_text(
                        " ", strip=True
                    ).lower()
                    if unit_index < len(next_columns)
                    else ""
                )
                if not next_label and "kcal" in next_unit:
                    value = next_columns[basis_index].get_text(
                        " ", strip=True
                    )
                elif "kj" in unit:
                    amount = re.search(r"[\d.,]+", value)
                    if amount:
                        value = f"{amount.group()} kJ"
            elif label.startswith("energy") and not re.search(
                r"kcal\b", value, re.I
            ):
                next_columns = (
                    table_rows[row_index + 1]
                    if row_index + 1 < len(table_rows)
                    else []
                )
                next_label = (
                    next_columns[0].get_text(" ", strip=True)
                    if next_columns
                    else ""
                )
                next_value = (
                    next_columns[basis_index].get_text(" ", strip=True)
                    if basis_index < len(next_columns)
                    else ""
                )
                if not next_label and re.search(r"kcal\b", next_value, re.I):
                    value = next_value
            rows.append((label, value))
    else:
        heading = soup.find(
            lambda tag: tag.name in {"h2", "h3"}
            and tag.get_text(" ", strip=True).lower() == "nutritional data"
        )
        content = heading.find_next_sibling() if heading else None
        if not content:
            return {}, None
        content = deepcopy(content)
        for line_break in content.find_all("br"):
            line_break.replace_with("\n")
        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in content.get_text("", strip=False).splitlines()
        ]
        lines = [line for line in lines if line]
        basis_text = " ".join(lines[:4]).lower()
        rows = []
        for index, line in enumerate(lines):
            if line.lower().startswith("energy"):
                energy_lines = lines[index:index + 3]
                kcal_line = next(
                    (
                        re.fullmatch(r"kcal\s*([\d.,]+)", candidate, re.I)
                        for candidate in energy_lines[1:]
                        if re.fullmatch(
                            r"kcal\s*[\d.,]+", candidate, re.I
                        )
                    ),
                    None,
                )
                energy = kcal_line or re.search(
                    r"([\d.,]+)\s*kcal\b", " ".join(energy_lines), re.I
                )
                if energy:
                    rows.append(("energy", energy.group(1)))
                continue
            rows.append((line.lower(), line))

    if "100ml" in basis_text or "100 ml" in basis_text:
        basis = "per_100ml"
    elif "100g" in basis_text or "100 g" in basis_text:
        basis = "per_100g"
    elif re.search(
        r"\beach\b|\bper\s+(?:item|serving|portion)\b|"
        r"\bper\s+(?:average\s+)?[a-z][a-z-]*\b",
        basis_text,
    ):
        basis = "per_item"
    elif re.search(
        r"\bper\s+\d+\s*/\s*\d+", basis_text
    ):
        basis = "per_item"
    else:
        basis = None

    nutrition = {}
    if serving_size_g is not None:
        nutrition["serving_size_g"] = serving_size_g
    if serving_unit is not None:
        nutrition["serving_unit"] = serving_unit
    for label, value in rows:
        normalized_label = re.sub(r"[^a-z]+", " ", label).strip()
        for field, terms in labels.items():
            if any(
                normalized_label == term
                or normalized_label.startswith(f"{term} ")
                for term in terms
            ):
                if field == "energy_kcal":
                    match = re.search(r"([\d.,]+)\s*kcal", value, re.I)
                    if match:
                        value = match.group(1)
                    elif table and re.search(r"\bkcal\b", normalized_label):
                        match = re.search(
                            r"\(\s*[\d.,]+\s*\)\s*([\d.,]+)", value
                        )
                        if match:
                            value = match.group(1)
                elif not table:
                    match = re.search(r"<\s*[\d.,]+|[\d.,]+", value)
                    if match:
                        value = match.group()
                nutrition[field] = value
                break
    return nutrition, basis


def _extract_product(
    session: requests.Session, url: str, category_name: str
) -> Mapping[str, object] | None:
    try:
        response = session.get(url, headers=REQUEST_HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException as error:
        logger.debug("Could not fetch product page %s: %s", url, error)
        return None

    soup = BeautifulSoup(response.content, "html.parser")
    product = _product_schema(soup)
    offers = product.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        offers = {}

    title_meta = soup.find("meta", property="og:title")
    price_element = soup.find(attrs={"data-test": "price-container"})
    price_meta = soup.find("meta", property="product:price:amount")
    listing_name = _first_value(
        product.get("name"),
        title_meta.get("content") if title_meta else None,
        soup.title.get_text(" ", strip=True) if soup.title else None,
    )
    if not listing_name:
        heading = soup.find("h1")
        listing_name = heading.get_text(" ", strip=True) if heading else None

    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    if not image:
        image_meta = soup.find("meta", property="og:image")
        image = image_meta.get("content") if image_meta else None

    package_size = _first_value(
        product.get("size"), product.get("weight"), listing_name
    )
    count_pack = bool(
        package_size
        and re.search(
            r"\d+(?:[.,]\d+)?\s*(?:per\s+pack|pack)\b",
            package_size,
            re.I,
        )
    )
    nutrition_table, nutrition_basis = _nutrition_table(
        soup, listing_name, prefer_per_item=count_pack
    )
    availability = str(offers.get("availability", "")).lower()
    page_text = soup.get_text(" ", strip=True).lower()
    out_of_stock = "outofstock" in availability or any(
        phrase in page_text
        for phrase in ("out of stock", "sold out", "currently unavailable")
    )

    return {
        "product": product,
        "source_url": url,
        "category_name": category_name,
        "listing_name": listing_name,
        "price": _first_value(
            offers.get("price"),
            price_element.get_text(" ", strip=True) if price_element else None,
            price_meta.get("content") if price_meta else None,
        ),
        "nutrition_table": nutrition_table,
        "nutrition_basis": nutrition_basis,
        "image_url": image,
        "out_of_stock": out_of_stock,
    }


def extract_products_with_stats() -> ExtractionResult:
    """Crawl product pages and return results with extraction counts."""
    product_categories = _crawl_product_categories()
    products = []
    failed_count = 0
    with requests.Session() as session:
        for processed_count, (url, category_name) in enumerate(
            sorted(product_categories.items()), start=1
        ):
            product = _extract_product(session, url, category_name)
            if product is not None:
                products.append(product)
            else:
                failed_count += 1
            if processed_count % EXTRACTION_PROGRESS_INTERVAL == 0:
                logger.debug(
                    "Extraction progress: %d/%d product pages processed; "
                    "%d failed.",
                    processed_count,
                    len(product_categories),
                    failed_count,
                )
    return ExtractionResult(
        products=products,
        discovered_count=len(product_categories),
        failed_count=failed_count,
    )


def extract_products() -> list[Mapping[str, object]]:
    """Crawl Morrisons categories and return raw product-page mappings."""
    return extract_products_with_stats().products
