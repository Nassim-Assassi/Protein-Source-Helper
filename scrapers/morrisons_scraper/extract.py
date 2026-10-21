"""Extract raw product data from Morrisons grocery pages."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
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
}
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": f"{BASE_URL}/",
}


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Products extracted and counts for discovered and failed product URLs."""

    products: list[Mapping[str, object]]
    discovered_count: int
    failed_count: int


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
            for category_url in sorted(category_urls):
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


def _nutrition_table(soup: BeautifulSoup) -> tuple[dict[str, str], str | None]:
    table = soup.find("table", class_=re.compile("nutrition", re.I))
    if not table:
        return {}, None

    header_row = table.find("tr")
    headers = header_row.find_all(["th", "td"]) if header_row else []
    basis_text = (
        headers[1].get_text(" ", strip=True).lower()
        if len(headers) > 1
        else table.get_text(" ", strip=True).lower()
    )
    if "100ml" in basis_text or "100 ml" in basis_text:
        basis = "per_100ml"
    elif "100g" in basis_text or "100 g" in basis_text:
        basis = "per_100g"
    elif "per item" in basis_text or "per serving" in basis_text:
        basis = "per_item"
    else:
        basis = None

    labels = {
        "energy_kcal": ("energy",),
        "protein_g": ("protein",),
        "carbohydrates_g": ("carbohydrate",),
        "sugars_g": ("sugars", "sugar"),
        "saturates_g": ("saturates", "saturated fat"),
        "fat_g": ("fat",),
        "fibre_g": ("fibre", "fiber"),
        "salt_g": ("salt",),
    }
    nutrition = {}
    for row in table.find_all("tr"):
        columns = row.find_all(["th", "td"])
        if len(columns) < 2:
            continue
        label = columns[0].get_text(" ", strip=True).lower()
        value = columns[1].get_text(" ", strip=True)
        for field, terms in labels.items():
            if any(label == term or label.startswith(f"{term} ") for term in terms):
                if field == "energy_kcal":
                    match = re.search(r"([\d.,]+)\s*kcal", value, re.I)
                    if match:
                        value = match.group(1)
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
        logger.warning("Could not fetch product page %s: %s", url, error)
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

    nutrition_table, nutrition_basis = _nutrition_table(soup)
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
        for url, category_name in sorted(product_categories.items()):
            product = _extract_product(session, url, category_name)
            if product is not None:
                products.append(product)
            else:
                failed_count += 1
    return ExtractionResult(
        products=products,
        discovered_count=len(product_categories),
        failed_count=failed_count,
    )


def extract_products() -> list[Mapping[str, object]]:
    """Crawl Morrisons categories and return raw product-page mappings."""
    return extract_products_with_stats().products
