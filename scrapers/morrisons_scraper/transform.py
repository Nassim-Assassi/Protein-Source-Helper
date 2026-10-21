"""Transform raw Morrisons product mappings into loader rows."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from scrapers.constants import PRODUCT_COLUMNS
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


def _energy_kcal(value: object) -> Decimal | None:
    if value is None:
        return None
    match = re.search(r"([\d.,]+)\s*kcal", str(value), re.I)
    return _decimal(match.group(1) if match else value)


def _package_quantity(
        product: Mapping[str, Any], listing_name: str | None
) -> tuple[Decimal | None, str | None]:
    values = [product.get("weight"), product.get("size"),
              product.get("description")]
    if listing_name:
        values.append(listing_name)
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
        match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|litres?|liters?)\b",
            str(value or ""),
            re.I,
        )
        if not match:
            continue
        quantity = _decimal(match.group(1))
        unit = match.group(2).lower()
        factor, normalized_unit = _UNIT_FACTORS[unit]
        return quantity * factor if quantity is not None else None, normalized_unit
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
            else _decimal(raw_value)
        )

    if values["salt_g"] is None:
        sodium = _decimal(schema_nutrition.get("sodiumContent"))
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
    normalized = (value or "").lower().replace(" ", "")
    if "100ml" in normalized:
        return "per_100ml"
    if "100g" in normalized:
        return "per_100g"
    if "peritem" in normalized or "perserving" in normalized:
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
    package_quantity, package_unit = _package_quantity(product, listing_name)
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
) -> pd.DataFrame:
    """Normalize raw product mappings into the loader's product columns."""
    rows = []
    skipped_count = 0
    for product in products:
        try:
            rows.append(_transform_product(product))
        except ValueError as error:
            skipped_count += 1
            logger.warning("Skipping invalid Morrisons product: %s", error)
    logger.info(
        "Transformation finished: %d products transformed, %d invalid rows skipped.",
        len(rows),
        skipped_count,
    )
    return pd.DataFrame(rows, columns=PRODUCT_COLUMNS)
