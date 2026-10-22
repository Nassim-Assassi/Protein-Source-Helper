"""
Load data into the PostgreSQL database for an individual retailer scrape run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import psycopg
from psycopg import Cursor

from scrapers.config import Config
from scrapers.constants import PRODUCT_COLUMNS
from scrapers.retailer_config import RetailerConfig


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Summarize data added during a scrape load."""

    loaded_count: int
    new_brand_count: int
    new_product_count: int
    new_retailer_category_count: int


def _connect(config: type[Config]) -> psycopg.Connection[Any]:
    """Open a PostgreSQL connection using required DATABASE_* settings."""
    required = Config._REQUIRED_SETTINGS
    missing = [name for name in required if not getattr(config, name, None)]
    if missing:
        raise RuntimeError(f"Missing database settings: {', '.join(missing)}")
    try:
        port = int(config.DATABASE_PORT)
    except ValueError as error:
        raise RuntimeError("DATABASE_PORT must be an integer") from error
    return psycopg.connect(
        host=config.DATABASE_HOST,
        port=port,
        dbname=config.DATABASE_NAME,
        user=config.DATABASE_USER,
        password=config.DATABASE_PASSWORD,
        connect_timeout=10,
    )


def _fetch_required_id(cursor: Cursor[Any], lookup_label: str, query: str, params: tuple[Any, ...]) -> int:
    """Run a lookup query and raise a clear error when it returns no row."""
    cursor.execute(query, params)
    result = cursor.fetchone()
    if result is None or result[0] is None:
        raise RuntimeError(f"No {lookup_label} row found for query: {query}")
    return result[0]


def _resolve_brand_id(cursor: Cursor[Any], brand_name: str) -> tuple[int, bool]:
    """Resolve a brand by name, inserting it if necessary. Return its ID and whether it was created."""
    cursor.execute(
        """
        INSERT INTO public.brand (brand_name)
        VALUES (%s)
        ON CONFLICT (brand_name) DO NOTHING
        RETURNING brand_id
        """,
        (brand_name,),
    )
    result = cursor.fetchone()
    if result is not None:
        return result[0], True
    return _fetch_required_id(
        cursor,
        "brand",
        "SELECT brand_id FROM public.brand WHERE brand_name = %s",
        (brand_name,),
    ), False


def _resolve_canonical_product_id(
    cursor: Cursor[Any],
    retailer_name: str,
    retailer_listing_name: str,
    barcode_gtin: str | None,
    brand_id: int | None,
) -> tuple[int, bool]:
    """Resolve by GTIN when present; otherwise match or create a retailer-scoped product.
    Return its ID and whether it was created.
    """
    canonical_product_name = (
        retailer_listing_name
        if barcode_gtin is not None
        else f"{retailer_name}_{retailer_listing_name}"
    )
    cursor.execute(
        """
        INSERT INTO public.canonical_product (
            canonical_product_name, barcode_gtin, brand_id
        )
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING canonical_product_id
        """,
        (canonical_product_name, barcode_gtin, brand_id),
    )
    result = cursor.fetchone()
    if result is not None:
        return result[0], True

    match_condition = (
        "barcode_gtin = %s"
        if barcode_gtin is not None
        else "canonical_product_name = %s AND barcode_gtin IS NULL"
    )
    match_value = barcode_gtin or canonical_product_name
    if brand_id is None:
        query = f"""
            SELECT canonical_product_id
            FROM public.canonical_product
            WHERE {match_condition}
            """
        params = (match_value,)
    else:
        query = f"""
            UPDATE public.canonical_product
            SET brand_id = COALESCE(brand_id, %s)
            WHERE {match_condition}
            RETURNING canonical_product_id
            """
        params = (brand_id, match_value)
    cursor.execute(query, params)

    result = cursor.fetchone()
    if result is None:
        raise RuntimeError(
            "Canonical product insert conflicted without a matching row")
    return result[0], False


def _resolve_retailer_category_id(
    cursor: Cursor[Any], retailer_id: int, category_name: str
) -> tuple[int, bool]:
    cursor.execute(
        """
        INSERT INTO public.retailer_category (
            retailer_id, retailer_category_name
        )
        VALUES (%s, %s)
        ON CONFLICT (retailer_id, retailer_category_name) DO NOTHING
        RETURNING retailer_category_id
        """,
        (retailer_id, category_name),
    )
    result = cursor.fetchone()
    if result is not None:
        return result[0], True
    return _fetch_required_id(
        cursor,
        "retailer category",
        """
        SELECT retailer_category_id
        FROM public.retailer_category
        WHERE retailer_id = %s AND retailer_category_name = %s
        """,
        (retailer_id, category_name),
    ), False


def _resolve_retailer_id(cursor: Cursor[Any], retailer: RetailerConfig) -> int:
    """Resolve a retailer by name, inserting it if necessary."""
    cursor.execute(
        """
        INSERT INTO public.retailer (retailer_name, retailer_url)
        VALUES (%s, %s)
        ON CONFLICT (retailer_name) DO NOTHING
        RETURNING retailer_id
        """,
        (retailer.name, retailer.url),
    )
    result = cursor.fetchone()
    if result is not None:
        return result[0]
    return _fetch_required_id(
        cursor,
        "retailer",
        "SELECT retailer_id FROM public.retailer WHERE retailer_name = %s",
        (retailer.name,),
    )


def _resolve_retailer_listing_id(
    cursor: Cursor[Any],
    retailer_id: int,
    canonical_product_id: int,
    retailer_category_id: int | None,
    external_id: str | None,
    listing_name: str,
    source_url: str,
    image_url: str | None,
) -> int:
    """Insert or update a listing using its retailer ID or source URL identity."""
    listing_fields = (
        canonical_product_id,
        retailer_category_id,
        listing_name,
        source_url,
        image_url,
    )
    if external_id is not None:
        cursor.execute(
            """
            INSERT INTO public.retailer_listing (
                canonical_product_id, retailer_category_id, retailer_id,
                retailer_listing_external_id, retailer_listing_name,
                retailer_listing_source_url, retailer_listing_image_url
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (retailer_id, retailer_listing_external_id)
                WHERE retailer_listing_external_id IS NOT NULL
            DO UPDATE SET
                canonical_product_id = EXCLUDED.canonical_product_id,
                retailer_category_id = EXCLUDED.retailer_category_id,
                retailer_listing_name = EXCLUDED.retailer_listing_name,
                retailer_listing_source_url = EXCLUDED.retailer_listing_source_url,
                retailer_listing_image_url = EXCLUDED.retailer_listing_image_url,
                retailer_listing_active = true
            RETURNING retailer_listing_id
            """,
            (*listing_fields[:2], retailer_id,
             external_id, *listing_fields[2:]),
        )
    else:
        cursor.execute(
            """
            INSERT INTO public.retailer_listing (
                canonical_product_id, retailer_category_id, retailer_id,
                retailer_listing_external_id, retailer_listing_name,
                retailer_listing_source_url, retailer_listing_image_url
            )
            VALUES (%s, %s, %s, NULL, %s, %s, %s)
            ON CONFLICT (retailer_id, retailer_listing_source_url)
                WHERE retailer_listing_external_id IS NULL
            DO UPDATE SET
                canonical_product_id = EXCLUDED.canonical_product_id,
                retailer_category_id = EXCLUDED.retailer_category_id,
                retailer_listing_name = EXCLUDED.retailer_listing_name,
                retailer_listing_image_url = EXCLUDED.retailer_listing_image_url,
                retailer_listing_active = true
            RETURNING retailer_listing_id
            """,
            (*listing_fields[:2], retailer_id, *listing_fields[2:]),
        )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError(
            "Failed to resolve retailer listing id after insert or update"
        )
    return row[0]


def _row_value(row: dict[str, Any], column: str) -> Any:
    """Return a value from a row, converting NaN to None and extracting scalars."""
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _load_snapshot(
    cursor: Cursor[Any],
    retailer_id: int,
    retailer_listing_id: int,
    scrape_run_id: int,
    row: dict[str, Any],
) -> bool:
    """Insert a product snapshot and report whether a row was inserted."""
    cursor.execute(
        """
        INSERT INTO public.snapshot (
            retailer_id, retailer_listing_id, scrape_run_id,
            snapshot_price, snapshot_package_quantity,
            snapshot_package_unit, snapshot_energy_kcal,
            snapshot_protein_g, snapshot_carbohydrates_g,
            snapshot_sugars_g, snapshot_fat_g, snapshot_saturates_g,
            snapshot_fibre_g, snapshot_salt_g, snapshot_nutrition_basis,
            snapshot_nutrition_source, snapshot_out_of_stock
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (retailer_listing_id, scrape_run_id) DO NOTHING
        RETURNING snapshot_id
        """,
        (
            retailer_id,
            retailer_listing_id,
            scrape_run_id,
            _row_value(row, "price"),
            _row_value(row, "package_quantity"),
            _row_value(row, "package_unit"),
            _row_value(row, "energy_kcal"),
            _row_value(row, "protein_g"),
            _row_value(row, "carbohydrates_g"),
            _row_value(row, "sugars_g"),
            _row_value(row, "fat_g"),
            _row_value(row, "saturates_g"),
            _row_value(row, "fibre_g"),
            _row_value(row, "salt_g"),
            _row_value(row, "nutrition_basis"),
            _row_value(row, "nutrition_source"),
            _row_value(row, "out_of_stock") or False,
        ),
    )
    return cursor.fetchone() is not None


def load_scrape(
    connection: psycopg.Connection[Any],
    scrape_run_id: int,
    retailer: RetailerConfig,
    products: pd.DataFrame,
) -> LoadResult:
    """Load product rows and their snapshots for one retailer scrape."""
    if products.empty:
        raise ValueError("Product dataframe must not be empty")

    missing_columns = set(PRODUCT_COLUMNS) - set(products.columns)
    if missing_columns:
        raise ValueError(
            f"Missing product columns: {', '.join(sorted(missing_columns))}"
        )

    for column in ("listing_name", "source_url"):
        invalid_values = products[column].isna() | (
            products[column].astype("string").str.strip().eq("")
        )
        if invalid_values.any():
            raise ValueError(f"Product {column} values must not be empty")

    with connection.transaction(), connection.cursor() as cursor:
        retailer_id = _resolve_retailer_id(cursor, retailer)
        loaded_count = 0
        new_brand_count = 0
        new_product_count = 0
        new_retailer_category_count = 0

        for row in products.loc[:, list(PRODUCT_COLUMNS)].to_dict(orient="records"):
            listing_name = _row_value(row, "listing_name")
            source_url = _row_value(row, "source_url")
            brand_name = _row_value(row, "brand_name")
            barcode_gtin = _row_value(row, "barcode_gtin")
            if barcode_gtin is not None:
                barcode_gtin = str(barcode_gtin).strip() or None
            category_name = _row_value(row, "category_name")

            brand_id = None
            if brand_name:
                brand_id, brand_created = _resolve_brand_id(
                    cursor, str(brand_name))
                new_brand_count += brand_created

            canonical_product_id, product_created = _resolve_canonical_product_id(
                cursor,
                retailer.name,
                str(listing_name),
                barcode_gtin,
                brand_id,
            )
            new_product_count += product_created

            retailer_category_id = None
            if category_name:
                retailer_category_id, category_created = _resolve_retailer_category_id(
                    cursor, retailer_id, str(category_name)
                )
                new_retailer_category_count += category_created

            external_id = _row_value(row, "external_id")
            image_url = _row_value(row, "image_url")
            retailer_listing_id = _resolve_retailer_listing_id(
                cursor,
                retailer_id,
                canonical_product_id,
                retailer_category_id,
                str(external_id) if external_id is not None else None,
                str(listing_name),
                str(source_url),
                str(image_url) if image_url is not None else None,
            )

            if _load_snapshot(
                cursor, retailer_id, retailer_listing_id, scrape_run_id, row
            ):
                loaded_count += 1

        cursor.execute(
            """
            UPDATE public.scrape_run
            SET scrape_run_status = 'succeeded',
                scrape_run_finished_at = clock_timestamp()
            WHERE scrape_run_id = %s
            """,
            (scrape_run_id,),
        )

        return LoadResult(
            loaded_count=loaded_count,
            new_brand_count=new_brand_count,
            new_product_count=new_product_count,
            new_retailer_category_count=new_retailer_category_count,
        )
