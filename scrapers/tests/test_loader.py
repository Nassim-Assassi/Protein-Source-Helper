import logging
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from scrapers.constants import PRODUCT_COLUMNS
from scrapers.config import Config
from scrapers.etl_contracts import ScrapeRunMetrics
from scrapers.loader.load import (
    _connect,
    _stage_values,
    load_scrape,
)
from scrapers.retailer_config import RetailerConfig


class TestStageValues:
    def test_uses_retailer_scoped_name_when_gtin_is_missing(self) -> None:
        row = {column: None for column in PRODUCT_COLUMNS}
        row.update(
            {
                "listing_name": "Product",
                "source_url": "https://example.com/product",
                "barcode_gtin": "  ",
                "out_of_stock": False,
            }
        )

        values = _stage_values(row, 1, "Retailer")

        assert values[0] == 1
        assert values[1] == "Product"
        assert values[19] is None
        assert values[22] == "Retailer_Product"

    def test_preserves_gtin_canonical_name_and_text_ids(self) -> None:
        row = {column: None for column in PRODUCT_COLUMNS}
        row.update(
            {
                "listing_name": "Product",
                "source_url": "https://example.com/product",
                "external_id": 123,
                "barcode_gtin": 456,
                "out_of_stock": False,
            }
        )

        values = _stage_values(row, 2, "Retailer")

        assert values[17] == "123"
        assert values[19] == "456"
        assert values[22] == "Product"


class TestLoadScrape:
    @staticmethod
    def products_frame(**overrides: object) -> pd.DataFrame:
        row: dict[str, object] = {column: None for column in PRODUCT_COLUMNS}
        row.update(
            {
                "listing_name": "Product",
                "source_url": "https://example.com/product",
                **overrides,
            }
        )
        return pd.DataFrame([row], columns=PRODUCT_COLUMNS)

    def test_connect_is_blocked_in_tests(self) -> None:
        with pytest.raises(
            AssertionError, match="Tests must not connect to PostgreSQL"
        ):
            _connect(Config)

    def test_load_scrape_runs_in_transaction(self) -> None:
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        metrics = ScrapeRunMetrics(
            discovered_count=4,
            extracted_count=3,
            extraction_failed_count=1,
            transformed_count=2,
            transformation_skipped_count=1,
            extraction_duration_seconds=0.5,
            transformation_duration_seconds=0.2,
        )

        with (
            patch("scrapers.loader.load._resolve_retailer_id", return_value=1),
            patch("scrapers.loader.load._create_staging_table"),
            patch("scrapers.loader.load._copy_products_to_stage"),
            patch(
                "scrapers.loader.load._bulk_resolve_brands_and_categories",
                return_value=(0, 0),
            ),
            patch(
                "scrapers.loader.load._bulk_insert_canonical_products",
                return_value=0,
            ),
            patch("scrapers.loader.load._bulk_upsert_retailer_listings"),
            patch(
                "scrapers.loader.load._bulk_insert_snapshots", return_value=1
            ),
        ):
            result = load_scrape(
                connection,
                1,
                RetailerConfig("Retailer", "https://example.com"),
                self.products_frame(),
                metrics,
            )

        connection.transaction.assert_called_once()
        connection.cursor.assert_called_once()
        assert result.loaded_count == 1
        success_update = next(
            call for call in cursor.execute.call_args_list
            if "SET scrape_run_status = 'succeeded'" in call.args[0]
        )
        assert "scrape_run_loaded_count = %s" in success_update.args[0]
        assert success_update.args[1][:6] == (4, 3, 1, 2, 1, 1)
        assert success_update.args[1][6:8] == (0.5, 0.2)
        assert success_update.args[1][8] >= 0
        assert success_update.args[1][9] == 1
        assert metrics.loaded_count == 1

    def test_load_scrape_uses_bulk_operations_and_reports_new_rows(self) -> None:
        connection = MagicMock()
        products = pd.concat(
            [
                self.products_frame(brand_name="Brand", category_name="Meat"),
                self.products_frame(brand_name="Brand", category_name="Meat"),
            ],
            ignore_index=True,
        )

        with (
            patch("scrapers.loader.load._resolve_retailer_id", return_value=1),
            patch("scrapers.loader.load._create_staging_table"),
            patch("scrapers.loader.load._copy_products_to_stage") as copy_rows,
            patch(
                "scrapers.loader.load._bulk_resolve_brands_and_categories",
                return_value=(1, 1),
            ) as resolve_entities,
            patch(
                "scrapers.loader.load._bulk_insert_canonical_products",
                return_value=2,
            ) as insert_products,
            patch("scrapers.loader.load._bulk_upsert_retailer_listings") as upsert,
            patch(
                "scrapers.loader.load._bulk_insert_snapshots", return_value=2
            ),
        ):
            result = load_scrape(
                connection,
                1,
                RetailerConfig("Retailer", "https://example.com"),
                products,
            )

        copy_rows.assert_called_once()
        resolve_entities.assert_called_once_with(
            connection.cursor.return_value.__enter__.return_value, 1
        )
        insert_products.assert_called_once()
        upsert.assert_called_once()
        assert result.loaded_count == 2
        assert result.new_brand_count == 1
        assert result.new_product_count == 2
        assert result.new_retailer_category_count == 1

    @pytest.mark.parametrize(
        ("log_level", "expect_progress"),
        [(logging.DEBUG, True), (logging.INFO, False)],
    )
    def test_logs_load_progress_only_at_debug_level(
        self, caplog, log_level: int, expect_progress: bool
    ) -> None:
        connection = MagicMock()
        products = pd.concat(
            [self.products_frame()] * 100, ignore_index=True
        )
        caplog.set_level(log_level, logger="scrapers")

        with (
            patch("scrapers.loader.load._resolve_retailer_id", return_value=1),
            patch("scrapers.loader.load._create_staging_table"),
            patch(
                "scrapers.loader.load._bulk_resolve_brands_and_categories",
                return_value=(0, 0),
            ),
            patch(
                "scrapers.loader.load._bulk_insert_canonical_products",
                return_value=0,
            ),
            patch("scrapers.loader.load._bulk_upsert_retailer_listings"),
            patch("scrapers.loader.load._bulk_insert_snapshots", return_value=100),
        ):
            result = load_scrape(
                connection,
                1,
                RetailerConfig("Retailer", "https://example.com"),
                products,
            )

        assert result.loaded_count == 100
        progress_messages = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("Load progress:")
        ]
        assert bool(progress_messages) is expect_progress
        if expect_progress:
            assert "100/100" in progress_messages[0]

    def test_empty_products_fail_before_database_writes(self) -> None:
        connection = Mock()
        products = pd.DataFrame(columns=PRODUCT_COLUMNS)

        with pytest.raises(ValueError, match="must not be empty"):
            load_scrape(
                connection,
                1,
                RetailerConfig("Retailer", "https://example.com"),
                products,
            )

        connection.cursor.assert_not_called()

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("listing_name", None),
            ("listing_name", "  "),
            ("source_url", None),
            ("source_url", "  "),
        ],
    )
    def test_missing_identity_values_fail_before_database_writes(
            self, column: str, value: object
    ) -> None:
        connection = Mock()
        products = self.products_frame(**{column: value})

        with pytest.raises(ValueError, match=f"{column} values"):
            load_scrape(
                connection,
                1,
                RetailerConfig("Retailer", "https://example.com"),
                products,
            )

        connection.cursor.assert_not_called()
