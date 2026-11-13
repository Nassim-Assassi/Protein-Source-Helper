"""Transform raw Morrisons product mappings into loader rows."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from scrapers.constants import PRODUCT_COLUMNS
from scrapers.etl_contracts import TransformResult
from scrapers.logger_setup import logger

_NUTRITION_FIELDS = {
    "energy_kcal": ("calories", "energy"),
    "protein_g": ("proteinContent",),
    "carbohydrates_g": ("carbohydrateContent", "carbohydratesContent"),
    "sugars_g": ("sugarContent", "sugarsContent"),
    "fat_g": ("fatContent",),
    "saturates_g": ("saturatedFatContent", "saturatesContent"),
    "fibre_g": ("fiberContent", "fibreContent"),
    "salt_g": ("saltContent",),
}
_UNIT_FACTORS = {
    "kg": (Decimal("1000"), "g"),
    "g": (Decimal("1"), "g"),
    "l": (Decimal("1000"), "ml"),
    "litre": (Decimal("1000"), "ml"),
    "litres": (Decimal("1000"), "ml"),
    "liter": (Decimal("1000"), "ml"),
    "liters": (Decimal("1000"), "ml"),
    "ml": (Decimal("1"), "ml"),
}


def _first_value(*values: object) -> str | None:
    for value in values:
        if isinstance(value, Mapping):
            value = value.get("name") or value.get("value")
        if isinstance(value, list):
            value = next((item for item in value if item), None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value).replace(",", "."))
    if not match:
        return None
    try:
        return Decimal(match.group())
    except InvalidOperation:
        return None


def _nutrition_decimal(value: object) -> Decimal | None:
    if value is not None and re.match(r"\s*<\s*", str(value)):
        return Decimal("0")
    return _decimal(value)


def _energy_kcal(value: object) -> Decimal | None:
    if value is None:
        return None
    if re.match(r"\s*<\s*", str(value)):
        return Decimal("0")
    text = str(value)
    kcal_match = re.search(r"([\d.,]+)\s*kcal\b", text, re.I)
    if kcal_match:
        return _nutrition_decimal(kcal_match.group(1))

    match = re.search(r"([\d.,]+)\s*(kj|mj)\b", text, re.I)
    if not match:
        return _nutrition_decimal(value)

    amount = _nutrition_decimal(match.group(1))
    if amount is None:
        return amount
    kilojoules = amount * \
        Decimal("1000") if match.group(2).lower() == "mj" else amount
    return kilojoules / Decimal("4.184")


def _package_quantity(
    product: Mapping[str, Any],
    listing_name: str | None,
    serving_size_g: object = None,
    serving_unit: object = None,
) -> tuple[Decimal | None, str | None]:
    values = [product.get("weight"), product.get("size"),
              product.get("description")]
    if listing_name:
        values.append(listing_name)
    normalized_values = []
    for value in values:
        if isinstance(value, Mapping):
            unit = value.get("unitText") or value.get("unitCode") or ""
            unit = {
                "GRM": "g",
                "KGM": "kg",
                "MLT": "ml",
                "LTR": "l",
            }.get(str(unit).upper(), unit)
            value = f"{value.get('value', '')} {unit}"
        normalized_values.append(str(value or ""))
    values = normalized_values
    for value in values:
        multipack_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*[x×]\s*"
            r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|litres?|liters?)\b",
            value,
            re.I,
        )
        if multipack_match:
            pack_count = _decimal(multipack_match.group(1))
            item_quantity = _decimal(multipack_match.group(2))
            factor, normalized_unit = _UNIT_FACTORS[
                multipack_match.group(3).lower()
            ]
            if pack_count is not None and item_quantity is not None:
                return pack_count * item_quantity * factor, normalized_unit

    for value in values:
        pack_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(?:per\s+pack|pack)\b",
            value,
            re.I,
        )
        if pack_match:
            quantity = _decimal(pack_match.group(1))
            serving_weight = _decimal(serving_size_g)
            if quantity is not None and serving_weight is not None:
                return quantity * serving_weight, "g"
            return quantity, "each"
        servings_match = re.search(
            r"\b(\d+(?:[.,]\d+)?)\s+(?:servings?|portions?)\s+per\b",
            value,
            re.I,
        )
        if servings_match:
            quantity = _decimal(servings_match.group(1))
            serving_weight = _decimal(serving_size_g)
            if quantity is not None and serving_weight is not None:
                return quantity * serving_weight, "g"
        match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|litres?|liters?)\b",
            value,
            re.I,
        )
        if not match:
            continue
        quantity = _decimal(match.group(1))
        unit = match.group(2).lower()
        factor, normalized_unit = _UNIT_FACTORS[unit]
        return quantity * factor if quantity is not None else None, normalized_unit
    if listing_name and serving_unit:
        item_match = re.search(
            rf"\b(\d+(?:[.,]\d+)?)\b(?:\s+[a-z-]+)*\s+"
            rf"{re.escape(str(serving_unit))}s?\b",
            listing_name,
            re.I,
        )
        if item_match:
            quantity = _decimal(item_match.group(1))
            return quantity, "each" if quantity is not None else None
    return None, None


def _nutrition_values(
        product: Mapping[str, Any], raw_table: Mapping[str, Any]
) -> dict[str, Decimal | None]:
    schema_nutrition = product.get("nutrition") or {}
    if not isinstance(schema_nutrition, Mapping):
        schema_nutrition = {}

    values = {}
    for field, schema_keys in _NUTRITION_FIELDS.items():
        table_value = raw_table.get(field)
        schema_value = _first_value(
            *(schema_nutrition.get(key) for key in schema_keys)
        )
        raw_value = table_value if table_value is not None else schema_value
        values[field] = (
            _energy_kcal(raw_value)
            if field == "energy_kcal"
            else _nutrition_decimal(raw_value)
        )

    if values["salt_g"] is None:
        sodium = _nutrition_decimal(schema_nutrition.get("sodiumContent"))
        if sodium is not None:
            values["salt_g"] = sodium * Decimal("2.5")
    return values


def _nutrition_basis(
        raw_basis: object, product: Mapping[str, Any]
) -> str | None:
    value = _first_value(raw_basis)
    nutrition = product.get("nutrition") or {}
    if value is None and isinstance(nutrition, Mapping):
        value = _first_value(nutrition.get("servingSize"))
    normalized = re.sub(r"[\s_]+", "", (value or "").lower())
    if "100ml" in normalized:
        return "per_100ml"
    if "100g" in normalized:
        return "per_100g"
    if (
        "peritem" in normalized
        or "perserving" in normalized
        or normalized.startswith("each")
    ):
        return "per_item"
    return None


def _image_url(product: Mapping[str, Any], fallback: object) -> str | None:
    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, Mapping):
        image = image.get("url")
    return _first_value(image, fallback)


def _transform_product(raw: Mapping[str, Any]) -> dict[str, Any]:
    product = raw.get("product") or {}
    if not isinstance(product, Mapping):
        product = {}
    offers = product.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, Mapping):
        offers = {}

    listing_name = _first_value(raw.get("listing_name"), product.get("name"))
    source_url = _first_value(raw.get("source_url"))
    nutrition_table = raw.get("nutrition_table") or {}
    if not isinstance(nutrition_table, Mapping):
        nutrition_table = {}
    nutrition = _nutrition_values(product, nutrition_table)
    package_quantity, package_unit = _package_quantity(
        product,
        listing_name,
        nutrition_table.get("serving_size_g"),
        nutrition_table.get("serving_unit"),
    )
    nutrition_basis = _nutrition_basis(raw.get("nutrition_basis"), product)

    row = {
        "listing_name": listing_name,
        "source_url": source_url,
        "price": _decimal(_first_value(raw.get("price"), offers.get("price"))),
        "package_quantity": package_quantity,
        "package_unit": package_unit,
        "energy_kcal": nutrition["energy_kcal"],
        "protein_g": nutrition["protein_g"],
        "nutrition_basis": nutrition_basis,
        "external_id": _first_value(
            product.get("sku"), product.get(
                "productID"), product.get("mpn")
        ),
        "image_url": _image_url(product, raw.get("image_url")),
        "barcode_gtin": _first_value(
            product.get("gtin13"),
            product.get("gtin12"),
            product.get("gtin8"),
            product.get("gtin14"),
            product.get("gtin"),
        ),
        "brand_name": _first_value(product.get("brand")),
        "category_name": _first_value(
            raw.get("category_name"), product.get("category")
        ),
        **{
            field: nutrition[field]
            for field in (
                "carbohydrates_g",
                "sugars_g",
                "fat_g",
                "saturates_g",
                "fibre_g",
                "salt_g",
            )
        },
        "nutrition_source": source_url
        if any(value is not None for value in nutrition.values())
        else None,
        "out_of_stock": bool(raw.get("out_of_stock"))
        or "outofstock" in str(offers.get("availability", "")).lower(),
    }

    required_fields = (
        "listing_name",
        "source_url",
        "price",
        "package_quantity",
        "package_unit",
        "energy_kcal",
        "protein_g",
        "nutrition_basis",
    )
    missing = [field for field in required_fields if row[field] is None]
    if missing:
        raise ValueError(
            f"Product {listing_name or source_url or '<unknown>'} is missing "
            f"required fields: {', '.join(missing)}"
        )

    expected_package_units = {
        "per_100g": "g",
        "per_100ml": "ml",
        "per_item": "each",
    }
    expected_unit = expected_package_units[row["nutrition_basis"]]
    if row["package_unit"] != expected_unit:
        raise ValueError(
            f"Product {listing_name} has nutrition basis "
            f"{row['nutrition_basis']} but package unit {row['package_unit']}"
        )
    return row


def transform_products(
        products: Iterable[Mapping[str, Any]],
) -> TransformResult:
    """Normalize raw product mappings into the loader's product columns."""
    rows = []
    skipped_count = 0
    for product in products:
        try:
            rows.append(_transform_product(product))
        except ValueError as error:
            skipped_count += 1
            logger.debug("Skipping invalid Morrisons product: %s", error)
    return TransformResult(
        products=pd.DataFrame(rows, columns=PRODUCT_COLUMNS),
        skipped_count=skipped_count,
    )
