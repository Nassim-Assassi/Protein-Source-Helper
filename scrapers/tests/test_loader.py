from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from scrapers.constants import PRODUCT_COLUMNS
from scrapers.loader.load import (
    _resolve_brand_id,
    _resolve_canonical_product_id,
    load_scrape,
)
from scrapers.retailer_config import RetailerConfig


class TestResolveCanonicalProductId:
    def test_gtin_products_can_share_the_first_listing_name(self) -> None:
        cursor = Mock()
        cursor.fetchone.side_effect = [(101,), (102,)]

        first = _resolve_canonical_product_id(
            cursor, "Retailer", "Same product name", "111", None
        )
        second = _resolve_canonical_product_id(
            cursor, "Retailer", "Same product name", "222", None
        )

        assert first == (101, True)
        assert second == (102, True)
        assert cursor.execute.call_args_list[0].args[1] == (
            "Same product name",
            "111",
            None,
        )
        assert cursor.execute.call_args_list[1].args[1] == (
            "Same product name",
            "222",
            None,
        )
        assert all(
            "ON CONFLICT DO NOTHING" in call.args[0]
            for call in cursor.execute.call_args_list
        )

    def test_existing_gtin_gets_brand_only_when_missing(self) -> None:
        cursor = Mock()
        cursor.fetchone.side_effect = [None, (101,)]

        result = _resolve_canonical_product_id(
            cursor, "Retailer", "Updated listing name", "111", 7
        )

        assert result == (101, False)
        assert cursor.execute.call_count == 2
        assert "SET brand_id = COALESCE(brand_id, %s)" in cursor.execute.call_args.args[
            0]
        assert "WHERE barcode_gtin = %s" in cursor.execute.call_args.args[0]
        assert cursor.execute.call_args.args[1] == (7, "111")

    def test_existing_gtin_without_incoming_brand_is_not_updated(self) -> None:
        cursor = Mock()
        cursor.fetchone.side_effect = [None, (101,)]

        result = _resolve_canonical_product_id(
            cursor, "Retailer", "Product", "111", None
        )

        assert result == (101, False)
        assert cursor.execute.call_count == 2
        assert "SELECT canonical_product_id" in cursor.execute.call_args.args[0]

    def test_no_gtin_product_uses_retailer_scoped_name_on_conflict(self) -> None:
        cursor = Mock()
        cursor.fetchone.side_effect = [None, (101,)]

        result = _resolve_canonical_product_id(
            cursor, "Retailer", "Product", None, None
        )

        assert result == (101, False)
        assert cursor.execute.call_args_list[0].args[1] == (
            "Retailer_Product",
            None,
            None,
        )
        assert "canonical_product_name = %s AND barcode_gtin IS NULL" in (
            cursor.execute.call_args_list[1].args[0]
        )

    def test_missing_brand_lookup_raises_runtime_error(self) -> None:
        cursor = Mock()
        cursor.fetchone.side_effect = [None, None]

        with pytest.raises(RuntimeError, match="brand"):
            _resolve_brand_id(cursor, "Brand")


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

    def test_load_scrape_runs_in_transaction(self) -> None:
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value

        with (
            patch("scrapers.loader.load._resolve_retailer_id", return_value=1),
            patch("scrapers.loader.load._create_scrape_run", return_value=2),
            patch("scrapers.loader.load._resolve_brand_id",
                  return_value=(10, False)),
            patch(
                "scrapers.loader.load._resolve_canonical_product_id",
                return_value=(20, False),
            ),
            patch(
                "scrapers.loader.load._resolve_retailer_category_id",
                return_value=(30, False),
            ),
            patch(
                "scrapers.loader.load._resolve_retailer_listing_id",
                return_value=40,
            ),
            patch("scrapers.loader.load._load_snapshot", return_value=True),
        ):
            result = load_scrape(
                connection,
                1,
                RetailerConfig("Retailer", "https://example.com"),
                self.products_frame(),
            )

        connection.transaction.assert_called_once()
        connection.cursor.assert_called_once()
        assert result.loaded_count == 1

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
