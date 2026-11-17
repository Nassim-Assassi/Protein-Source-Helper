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
import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_ENV = PROJECT_ROOT / "test.env"
if TEST_ENV.exists():
    load_dotenv(TEST_ENV, override=False)


FIXTURE_PATH = Path(__file__).with_name("morrisons_test_loader_integration_fixture.csv")
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
                "SELECT count(*) FROM protein_source_helper.snapshot"
            )
            snapshot_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT count(*) FROM protein_source_helper.retailer_listing"
            )
            listing_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT snapshot_price
                FROM protein_source_helper.snapshot
                JOIN protein_source_helper.retailer_listing
                    USING (retailer_listing_id)
                WHERE retailer_listing_external_id = 'TEST001'
                """
            )
            snapshot_price = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT count(*)
                FROM protein_source_helper.canonical_product
                WHERE barcode_gtin = '05012345000001'
                """
            )
            shared_gtin_count = cursor.fetchone()[0]

        assert result.loaded_count == 10
        assert snapshot_count == 10
        assert listing_count == 10
        assert snapshot_price == Decimal("19.99")
        assert shared_gtin_count == 1
