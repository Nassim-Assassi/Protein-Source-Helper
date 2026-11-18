"""End-to-end PostgreSQL loading tests."""

from __future__ import annotations
from scrapers.retailer_config import RetailerConfig
from scrapers.loader.load import _connect, load_scrape
from scrapers.constants import DATABASE_SCHEMA
from scrapers.config import Config

import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.rows import dict_row
import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_ENV = PROJECT_ROOT / "test.env"
if TEST_ENV.exists():
    load_dotenv(TEST_ENV, override=False)


FIXTURE_PATH = Path(__file__).with_name(
    "morrisons_test_loader_integration_fixture.csv")
RETAILER = RetailerConfig(
    name="Morrisons",
    url="https://groceries.morrisons.com",
)

pytestmark = pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTING_DATABASE") != "true",
    reason="Set INTEGRATION_TESTING_DATABASE=true and use test.env",
)


@pytest.fixture
def integration_connection() -> Iterator[psycopg.Connection]:
    connection = _connect(Config)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass(%s)",
            (f"{DATABASE_SCHEMA}.scrape_batch",),
        )
        if cursor.fetchone()[0] is None:
            pytest.fail(
                "Integration database schema is missing; run "
                "database/initial_database_setup.sh test.env first"
            )

    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


class TestLoadScrapeIntegration:
    def test_load_fixture_matches_database_rows(
        self,
        integration_connection: psycopg.Connection,
    ) -> None:
        products = pd.read_csv(
            FIXTURE_PATH,
            dtype={"barcode_gtin": "string", "external_id": "string"},
        )

        assert len(products) == 10

        with integration_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO protein_source_helper.scrape_batch (scrape_batch_status)
                VALUES ('running')
                RETURNING scrape_batch_id
                """
            )
            batch_id = cursor.fetchone()[0]

            cursor.execute(
                """
                INSERT INTO protein_source_helper.retailer (retailer_name, retailer_url)
                VALUES (%s, %s)
                RETURNING retailer_id
                """,
                (RETAILER.name, RETAILER.url),
            )
            retailer_id = cursor.fetchone()[0]

            cursor.execute(
                """
                INSERT INTO protein_source_helper.scrape_run (
                    scrape_batch_id, retailer_id, scrape_run_status
                )
                VALUES (%s, %s, 'running')
                RETURNING scrape_run_id
                """,
                (batch_id, retailer_id),
            )
            scrape_run_id = cursor.fetchone()[0]

        result = load_scrape(
            integration_connection,
            scrape_run_id,
            RETAILER,
            products,
        )

        with integration_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE protein_source_helper.scrape_batch "
                "SET scrape_batch_status = 'succeeded', "
                "scrape_batch_finished_at = clock_timestamp() "
                "WHERE scrape_batch_id = %s",
                (batch_id,),
            )

            cursor.execute(
                """
                SELECT
                    count(DISTINCT listing.retailer_listing_id),
                    count(snapshot.snapshot_id)
                FROM protein_source_helper.snapshot AS snapshot
                JOIN protein_source_helper.retailer_listing AS listing
                    USING (retailer_listing_id)
                WHERE snapshot.scrape_run_id = %s
                """,
                (scrape_run_id,),
            )
            listing_count, snapshot_count = cursor.fetchone()

            with integration_connection.cursor(row_factory=dict_row) as row_cursor:
                row_cursor.execute(
                    """
                    SELECT
                        listing.retailer_listing_external_id AS external_id,
                        listing.canonical_product_id,
                        product.barcode_gtin,
                        product.canonical_product_name,
                        brand.brand_name,
                        brand.brand_id,
                        category.retailer_category_name AS category_name,
                        category.retailer_category_id,
                        listing.retailer_listing_image_url AS image_url,
                        snapshot.snapshot_price,
                        snapshot.snapshot_package_quantity,
                        snapshot.snapshot_package_unit,
                        snapshot.snapshot_energy_kcal,
                        snapshot.snapshot_protein_g,
                        snapshot.snapshot_nutrition_basis,
                        snapshot.snapshot_out_of_stock
                    FROM protein_source_helper.snapshot AS snapshot
                    JOIN protein_source_helper.retailer_listing AS listing
                        USING (retailer_listing_id)
                    JOIN protein_source_helper.canonical_product AS product
                        USING (canonical_product_id)
                    LEFT JOIN protein_source_helper.brand AS brand
                        USING (brand_id)
                    LEFT JOIN protein_source_helper.retailer_category AS category
                        USING (retailer_category_id)
                    WHERE snapshot.scrape_run_id = %s
                    """,
                    (scrape_run_id,),
                )
                rows = {
                    row["external_id"]: row
                    for row in row_cursor.fetchall()
                }

        assert result.loaded_count == 10
        assert (listing_count, snapshot_count) == (10, 10)
        assert set(rows) == {f"TEST{number:03}" for number in range(1, 11)}

        assert rows["TEST001"]["canonical_product_id"] == rows["TEST002"][
            "canonical_product_id"
        ]
        assert rows["TEST001"]["barcode_gtin"] == "05012345000001"
        assert rows["TEST009"]["barcode_gtin"] is None
        assert rows["TEST010"]["barcode_gtin"] is None
        assert rows["TEST009"]["canonical_product_id"] == rows["TEST010"][
            "canonical_product_id"
        ]

        assert rows["TEST001"]["brand_name"] == "Test Nutrition"
        assert rows["TEST001"]["brand_id"] == rows["TEST002"]["brand_id"]
        assert rows["TEST001"]["category_name"] == "Test Protein"
        assert rows["TEST001"]["retailer_category_id"] == rows["TEST002"][
            "retailer_category_id"
        ]

        assert rows["TEST003"]["image_url"] is None
        assert rows["TEST008"]["snapshot_out_of_stock"] is True
        assert rows["TEST001"]["snapshot_price"] == Decimal("19.99")
        assert rows["TEST001"]["snapshot_protein_g"] == Decimal("80.000")
        assert rows["TEST008"]["snapshot_package_quantity"] == Decimal(
            "330.000")
        assert rows["TEST008"]["snapshot_package_unit"] == "ml"
        assert rows["TEST008"]["snapshot_nutrition_basis"] == "per_100ml"
