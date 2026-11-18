"""
Load data into the PostgreSQL database for an individual retailer scrape run.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import pandas as pd
import psycopg
from psycopg import Cursor

from scrapers.config import Config
from scrapers.constants import DATABASE_SCHEMA, PRODUCT_COLUMNS
from scrapers.etl_contracts import LoadResult, ScrapeRunMetrics
from scrapers.logger_setup import logger
from scrapers.retailer_config import RetailerConfig

LOAD_PROGRESS_INTERVAL = 100
STAGING_TABLE = "loader_stage"


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


def _fetch_required_id(
    cursor: Cursor[Any], lookup_label: str, query: str, params: tuple[Any, ...]
) -> int:
    """Run a lookup query and raise a clear error when it returns no row."""
    cursor.execute(query, params)
    result = cursor.fetchone()
    if result is None or result[0] is None:
        raise RuntimeError(f"No {lookup_label} row found for query: {query}")
    return result[0]


def _resolve_retailer_id(cursor: Cursor[Any], retailer: RetailerConfig) -> int:
    """Resolve a retailer by name or URL, inserting it if necessary."""
    cursor.execute(
        f"""
        SELECT retailer_id
        FROM {DATABASE_SCHEMA}.retailer
        WHERE retailer_name = %s OR retailer_url = %s
        """,
        (retailer.name, retailer.url),
    )
    result = cursor.fetchone()
    if result is not None:
        return result[0]

    cursor.execute(
        f"""
        INSERT INTO {DATABASE_SCHEMA}.retailer (retailer_name, retailer_url)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
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
        f"""
        SELECT retailer_id
        FROM {DATABASE_SCHEMA}.retailer
        WHERE retailer_name = %s OR retailer_url = %s
        """,
        (retailer.name, retailer.url),
    )


def _row_value(row: dict[str, Any], column: str) -> Any:
    """Return a value from a row, converting NaN to None and extracting scalars."""
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _create_staging_table(cursor: Cursor[Any]) -> None:
    cursor.execute(
        f"""
        CREATE TEMP TABLE {STAGING_TABLE} (
            row_number bigint PRIMARY KEY,
            listing_name text NOT NULL,
            source_url text NOT NULL,
            price numeric,
            package_quantity numeric,
            package_unit text,
            energy_kcal numeric,
            protein_g numeric,
            carbohydrates_g numeric,
            sugars_g numeric,
            fat_g numeric,
            saturates_g numeric,
            fibre_g numeric,
            salt_g numeric,
            nutrition_basis text,
            nutrition_source text,
            out_of_stock boolean NOT NULL,
            external_id text,
            image_url text,
            barcode_gtin text,
            brand_name text,
            category_name text,
            canonical_product_name text NOT NULL,
            brand_id integer,
            retailer_category_id integer,
            canonical_product_id integer,
            retailer_listing_id integer
        ) ON COMMIT DROP
        """
    )


def _stage_values(row: dict[str, Any], row_number: int, retailer_name: str) -> tuple[Any, ...]:
    listing_name = str(_row_value(row, "listing_name"))
    source_url = str(_row_value(row, "source_url"))
    barcode_gtin = _row_value(row, "barcode_gtin")
    if barcode_gtin is not None:
        barcode_gtin = str(barcode_gtin).strip() or None
    brand_name = _row_value(row, "brand_name")
    category_name = _row_value(row, "category_name")
    external_id = _row_value(row, "external_id")
    image_url = _row_value(row, "image_url")
    if brand_name:
        brand_name = str(brand_name)
    else:
        brand_name = None
    if category_name:
        category_name = str(category_name)
    else:
        category_name = None

    return (
        row_number,
        listing_name,
        source_url,
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
        str(external_id) if external_id is not None else None,
        str(image_url) if image_url is not None else None,
        barcode_gtin,
        brand_name,
        category_name,
        listing_name if barcode_gtin is not None else f"{retailer_name}_{listing_name}",
    )


def _copy_products_to_stage(
    cursor: Cursor[Any],
    products: pd.DataFrame,
    retailer_name: str,
    load_started_at: float,
) -> None:
    columns = (
        "row_number, listing_name, source_url, price, package_quantity, "
        "package_unit, energy_kcal, protein_g, carbohydrates_g, sugars_g, "
        "fat_g, saturates_g, fibre_g, salt_g, nutrition_basis, "
        "nutrition_source, out_of_stock, external_id, image_url, "
        "barcode_gtin, brand_name, category_name, canonical_product_name"
    )
    with cursor.copy(
        f"COPY {STAGING_TABLE} ({columns}) FROM STDIN"
    ) as copy:
        rows = products.loc[:, list(PRODUCT_COLUMNS)].to_dict(orient="records")
        for processed_count, row in enumerate(rows, start=1):
            copy.write_row(_stage_values(row, processed_count, retailer_name))
            if processed_count % LOAD_PROGRESS_INTERVAL == 0:
                logger.debug(
                    "Load progress: %d/%d products staged; %.1fs elapsed.",
                    processed_count,
                    len(products),
                    perf_counter() - load_started_at,
                )
    cursor.execute(f"ANALYZE {STAGING_TABLE}")


def _bulk_resolve_brands_and_categories(
    cursor: Cursor[Any], retailer_id: int
) -> tuple[int, int]:
    cursor.execute(
        f"""
        INSERT INTO {DATABASE_SCHEMA}.brand (brand_name)
        SELECT brand_name
        FROM (
            SELECT DISTINCT brand_name
            FROM {STAGING_TABLE}
            WHERE brand_name IS NOT NULL
        ) AS staged_brands
        ORDER BY brand_name
        ON CONFLICT (brand_name) DO NOTHING
        RETURNING brand_id
        """
    )
    new_brand_count = len(cursor.fetchall())
    cursor.execute(
        f"""
        UPDATE {STAGING_TABLE} AS staged
        SET brand_id = brand.brand_id
        FROM {DATABASE_SCHEMA}.brand AS brand
        WHERE staged.brand_name = brand.brand_name
        """
    )

    cursor.execute(
        f"""
        INSERT INTO {DATABASE_SCHEMA}.retailer_category (
            retailer_id, retailer_category_name
        )
        SELECT %s, category_name
        FROM (
            SELECT DISTINCT category_name
            FROM {STAGING_TABLE}
            WHERE category_name IS NOT NULL
        ) AS staged_categories
        ORDER BY category_name
        ON CONFLICT (retailer_id, retailer_category_name) DO NOTHING
        RETURNING retailer_category_id
        """,
        (retailer_id,),
    )
    new_category_count = len(cursor.fetchall())
    cursor.execute(
        f"""
        UPDATE {STAGING_TABLE} AS staged
        SET retailer_category_id = category.retailer_category_id
        FROM {DATABASE_SCHEMA}.retailer_category AS category
        WHERE category.retailer_id = %s
            AND staged.category_name = category.retailer_category_name
        """,
        (retailer_id,),
    )
    return new_brand_count, new_category_count


def _bulk_insert_canonical_products(cursor: Cursor[Any]) -> int:
    candidates_ctes = f"""
        product_keys AS (
            SELECT
                barcode_gtin,
                CASE
                    WHEN barcode_gtin IS NULL THEN canonical_product_name
                END AS canonical_product_name,
                MIN(row_number) AS first_row_number
            FROM {STAGING_TABLE}
            GROUP BY
                barcode_gtin,
                CASE
                    WHEN barcode_gtin IS NULL THEN canonical_product_name
                END
        ),
        candidates AS (
            SELECT
                first_product.canonical_product_name,
                product_keys.barcode_gtin,
                (
                    SELECT brand_source.brand_id
                    FROM {STAGING_TABLE} AS brand_source
                    WHERE brand_source.brand_id IS NOT NULL
                        AND (
                            (
                                product_keys.barcode_gtin IS NOT NULL
                                AND brand_source.barcode_gtin = product_keys.barcode_gtin
                            )
                            OR (
                                product_keys.barcode_gtin IS NULL
                                AND brand_source.barcode_gtin IS NULL
                                AND brand_source.canonical_product_name =
                                    product_keys.canonical_product_name
                            )
                        )
                    ORDER BY brand_source.row_number
                    LIMIT 1
                ) AS brand_id
            FROM product_keys
            JOIN {STAGING_TABLE} AS first_product
                ON first_product.row_number = product_keys.first_row_number
        )
    """
    cursor.execute(
        f"""
        WITH {candidates_ctes}
        INSERT INTO {DATABASE_SCHEMA}.canonical_product (
            canonical_product_name, barcode_gtin, brand_id
        )
        SELECT canonical_product_name, barcode_gtin, brand_id
        FROM candidates
        WHERE true
        ORDER BY barcode_gtin NULLS FIRST, canonical_product_name
        ON CONFLICT DO NOTHING
        RETURNING canonical_product_id
        """
    )
    new_product_count = len(cursor.fetchall())

    cursor.execute(
        f"""
        WITH {candidates_ctes}
        UPDATE {DATABASE_SCHEMA}.canonical_product AS product
        SET brand_id = candidates.brand_id
        FROM candidates
        WHERE product.brand_id IS NULL
            AND candidates.brand_id IS NOT NULL
            AND (
                (
                    candidates.barcode_gtin IS NOT NULL
                    AND product.barcode_gtin = candidates.barcode_gtin
                )
                OR (
                    candidates.barcode_gtin IS NULL
                    AND product.barcode_gtin IS NULL
                    AND product.canonical_product_name =
                        candidates.canonical_product_name
                )
            )
        """
    )
    cursor.execute(
        f"""
        UPDATE {STAGING_TABLE} AS staged
        SET canonical_product_id = product.canonical_product_id
        FROM {DATABASE_SCHEMA}.canonical_product AS product
        WHERE staged.barcode_gtin IS NOT NULL
            AND product.barcode_gtin = staged.barcode_gtin
        """
    )
    cursor.execute(
        f"""
        UPDATE {STAGING_TABLE} AS staged
        SET canonical_product_id = product.canonical_product_id
        FROM {DATABASE_SCHEMA}.canonical_product AS product
        WHERE staged.barcode_gtin IS NULL
            AND product.barcode_gtin IS NULL
            AND product.canonical_product_name = staged.canonical_product_name
        """
    )
    return new_product_count


def _bulk_upsert_retailer_listings(
    cursor: Cursor[Any], retailer_id: int
) -> None:
    cursor.execute(
        f"""
        WITH latest_listings AS (
            SELECT DISTINCT ON (external_id) *
            FROM {STAGING_TABLE}
            WHERE external_id IS NOT NULL
            ORDER BY external_id, row_number DESC
        )
        INSERT INTO {DATABASE_SCHEMA}.retailer_listing (
            canonical_product_id, retailer_category_id, retailer_id,
            retailer_listing_external_id, retailer_listing_name,
            retailer_listing_source_url, retailer_listing_image_url
        )
        SELECT
            canonical_product_id, retailer_category_id, %s, external_id,
            listing_name, source_url, image_url
        FROM latest_listings
        WHERE true
        ORDER BY external_id
        ON CONFLICT (retailer_id, retailer_listing_external_id)
            WHERE retailer_listing_external_id IS NOT NULL
        DO UPDATE SET
            canonical_product_id = EXCLUDED.canonical_product_id,
            retailer_category_id = EXCLUDED.retailer_category_id,
            retailer_listing_name = EXCLUDED.retailer_listing_name,
            retailer_listing_source_url = EXCLUDED.retailer_listing_source_url,
            retailer_listing_image_url = EXCLUDED.retailer_listing_image_url,
            retailer_listing_active = true
        """,
        (retailer_id,),
    )
    cursor.execute(
        f"""
        WITH latest_listings AS (
            SELECT DISTINCT ON (source_url) *
            FROM {STAGING_TABLE}
            WHERE external_id IS NULL
            ORDER BY source_url, row_number DESC
        )
        INSERT INTO {DATABASE_SCHEMA}.retailer_listing (
            canonical_product_id, retailer_category_id, retailer_id,
            retailer_listing_external_id, retailer_listing_name,
            retailer_listing_source_url, retailer_listing_image_url
        )
        SELECT
            canonical_product_id, retailer_category_id, %s, NULL,
            listing_name, source_url, image_url
        FROM latest_listings
        WHERE true
        ORDER BY source_url
        ON CONFLICT (retailer_id, retailer_listing_source_url)
            WHERE retailer_listing_external_id IS NULL
        DO UPDATE SET
            canonical_product_id = EXCLUDED.canonical_product_id,
            retailer_category_id = EXCLUDED.retailer_category_id,
            retailer_listing_name = EXCLUDED.retailer_listing_name,
            retailer_listing_image_url = EXCLUDED.retailer_listing_image_url,
            retailer_listing_active = true
        """,
        (retailer_id,),
    )
    cursor.execute(
        f"""
        UPDATE {STAGING_TABLE} AS staged
        SET retailer_listing_id = listing.retailer_listing_id
        FROM {DATABASE_SCHEMA}.retailer_listing AS listing
        WHERE staged.external_id IS NOT NULL
            AND listing.retailer_id = %s
            AND listing.retailer_listing_external_id = staged.external_id
        """,
        (retailer_id,),
    )
    cursor.execute(
        f"""
        UPDATE {STAGING_TABLE} AS staged
        SET retailer_listing_id = listing.retailer_listing_id
        FROM {DATABASE_SCHEMA}.retailer_listing AS listing
        WHERE staged.external_id IS NULL
            AND listing.retailer_id = %s
            AND listing.retailer_listing_external_id IS NULL
            AND listing.retailer_listing_source_url = staged.source_url
        """,
        (retailer_id,),
    )


def _bulk_insert_snapshots(
    cursor: Cursor[Any], retailer_id: int, scrape_run_id: int
) -> int:
    cursor.execute(
        f"""
        WITH first_external_snapshot AS (
            SELECT DISTINCT ON (external_id)
                retailer_listing_id, price, package_quantity, package_unit,
                energy_kcal, protein_g, carbohydrates_g, sugars_g, fat_g,
                saturates_g, fibre_g, salt_g, nutrition_basis,
                nutrition_source, out_of_stock, external_id AS identity
            FROM {STAGING_TABLE}
            WHERE external_id IS NOT NULL
            ORDER BY external_id, row_number
        ),
        first_url_snapshot AS (
            SELECT DISTINCT ON (source_url)
                retailer_listing_id, price, package_quantity, package_unit,
                energy_kcal, protein_g, carbohydrates_g, sugars_g, fat_g,
                saturates_g, fibre_g, salt_g, nutrition_basis,
                nutrition_source, out_of_stock, source_url AS identity
            FROM {STAGING_TABLE}
            WHERE external_id IS NULL
            ORDER BY source_url, row_number
        ),
        snapshots AS (
            SELECT * FROM first_external_snapshot
            UNION ALL
            SELECT * FROM first_url_snapshot
        )
        INSERT INTO {DATABASE_SCHEMA}.snapshot (
            retailer_id, retailer_listing_id, scrape_run_id,
            snapshot_price, snapshot_package_quantity,
            snapshot_package_unit, snapshot_energy_kcal,
            snapshot_protein_g, snapshot_carbohydrates_g,
            snapshot_sugars_g, snapshot_fat_g, snapshot_saturates_g,
            snapshot_fibre_g, snapshot_salt_g, snapshot_nutrition_basis,
            snapshot_nutrition_source, snapshot_out_of_stock
        )
        SELECT
            %s, retailer_listing_id, %s, price, package_quantity,
            package_unit, energy_kcal, protein_g, carbohydrates_g,
            sugars_g, fat_g, saturates_g, fibre_g, salt_g,
            nutrition_basis, nutrition_source, out_of_stock
        FROM snapshots
        WHERE true
        ORDER BY retailer_listing_id
        ON CONFLICT (retailer_listing_id, scrape_run_id) DO NOTHING
        RETURNING snapshot_id
        """,
        (retailer_id, scrape_run_id),
    )
    return len(cursor.fetchall())


def load_scrape(
    connection: psycopg.Connection[Any],
    scrape_run_id: int,
    retailer: RetailerConfig,
    products: pd.DataFrame,
    metrics: ScrapeRunMetrics | None = None,
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

    load_started_at = perf_counter()
    with connection.transaction(), connection.cursor() as cursor:
        run_metrics = metrics or ScrapeRunMetrics()
        retailer_id = _resolve_retailer_id(cursor, retailer)
        _create_staging_table(cursor)
        _copy_products_to_stage(
            cursor, products, retailer.name, load_started_at)
        new_brand_count, new_retailer_category_count = (
            _bulk_resolve_brands_and_categories(cursor, retailer_id)
        )
        new_product_count = _bulk_insert_canonical_products(cursor)
        _bulk_upsert_retailer_listings(cursor, retailer_id)
        loaded_count = _bulk_insert_snapshots(
            cursor, retailer_id, scrape_run_id
        )

        run_metrics.loaded_count = loaded_count
        run_metrics.load_duration_seconds = perf_counter() - load_started_at
        cursor.execute(
            f"""
            UPDATE {DATABASE_SCHEMA}.scrape_run
            SET scrape_run_status = 'succeeded',
                scrape_run_finished_at = clock_timestamp(),
                scrape_run_discovered_count = %s,
                scrape_run_extracted_count = %s,
                scrape_run_extraction_failed_count = %s,
                scrape_run_transformed_count = %s,
                scrape_run_transformation_skipped_count = %s,
                scrape_run_loaded_count = %s,
                scrape_run_extraction_duration_seconds = %s,
                scrape_run_transformation_duration_seconds = %s,
                scrape_run_load_duration_seconds = %s
            WHERE scrape_run_id = %s
            """,
            (
                run_metrics.discovered_count,
                run_metrics.extracted_count,
                run_metrics.extraction_failed_count,
                run_metrics.transformed_count,
                run_metrics.transformation_skipped_count,
                run_metrics.loaded_count,
                run_metrics.extraction_duration_seconds,
                run_metrics.transformation_duration_seconds,
                run_metrics.load_duration_seconds,
                scrape_run_id,
            ),
        )

        result = LoadResult(
            loaded_count=loaded_count,
            new_brand_count=new_brand_count,
            new_product_count=new_product_count,
            new_retailer_category_count=new_retailer_category_count,
        )

    logger.debug(
        "Load finished in %.1fs: %d/%d snapshots loaded.",
        perf_counter() - load_started_at,
        result.loaded_count,
        len(products),
    )
    return result
