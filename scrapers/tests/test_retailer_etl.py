from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

import pandas as pd
import pytest

from scrapers.loader.load import LoadResult
from scrapers.morrisons_scraper.extract import ExtractionResult
from scrapers.orchestrators import retailer_etl


class TestRunRetailerEtl:
    def test_extracts_transforms_and_loads_for_given_retailer(self) -> None:
        raw_products = [{"listing_name": "Product"}]
        extraction = ExtractionResult(raw_products, 2, 1)
        transformed_products = pd.DataFrame([{"listing_name": "Product"}])
        result = LoadResult(1, 0, 1, 1)
        connection = MagicMock()
        connection_context = MagicMock()
        connection_context.__enter__.return_value = connection
        retailer = retailer_etl.RetailerConfig(
            name="morrisons", url="https://groceries.morrisons.com"
        )
        extract_module = SimpleNamespace(
            extract_products_with_stats=MagicMock(return_value=extraction)
        )
        transform_module = SimpleNamespace(
            transform_products=MagicMock(return_value=transformed_products)
        )

        with (
            patch.object(
                retailer_etl, "initiate_scrape_run", return_value=99
            ) as initiate,
            patch.object(
                retailer_etl,
                "import_module",
                side_effect=[extract_module, transform_module],
            ) as import_scraper,
            patch.object(
                retailer_etl, "_connect", return_value=connection_context
            ) as connect,
            patch.object(retailer_etl, "load_scrape", return_value=result) as load,
            patch.object(retailer_etl, "fail_scrape_run") as fail_run,
        ):
            events = Mock()
            events.attach_mock(initiate, "initiate")
            events.attach_mock(import_scraper, "import_scraper")
            actual_result = retailer_etl.run_retailer_etl(
                42, "morrisons", "https://groceries.morrisons.com"
            )

        assert events.mock_calls[:2] == [
            call.initiate(42, retailer),
            call.import_scraper("scrapers.morrisons_scraper.extract"),
        ]
        assert import_scraper.call_args_list == [
            call("scrapers.morrisons_scraper.extract"),
            call("scrapers.morrisons_scraper.transform"),
        ]
        extract_module.extract_products_with_stats.assert_called_once_with()
        transform_module.transform_products.assert_called_once_with(
            raw_products)
        connect.assert_called_once_with(retailer_etl.Config)
        load.assert_called_once_with(
            connection, 99, retailer, transformed_products
        )
        fail_run.assert_not_called()
        assert actual_result is result

    def test_rejects_retailer_without_a_scraper(self) -> None:
        missing_module = ModuleNotFoundError(
            "No module", name="scrapers.Unknown_scraper"
        )
        with (
            patch.object(retailer_etl, "initiate_scrape_run", return_value=99),
            patch.object(retailer_etl, "fail_scrape_run") as fail_run,
            patch.object(
                retailer_etl, "import_module", side_effect=missing_module
            ),
        ):
            with pytest.raises(ValueError, match="No scraper modules found"):
                retailer_etl.run_retailer_etl(
                    42, "Unknown", "https://example.com"
                )

        fail_run.assert_called_once_with(
            99, "No scraper modules found for 'Unknown'"
        )

    def test_does_not_open_database_when_all_products_are_skipped(self) -> None:
        extraction = ExtractionResult([{"listing_name": "Incomplete"}], 1, 0)
        connection = MagicMock()
        connection_context = MagicMock()
        connection_context.__enter__.return_value = connection
        extract_module = SimpleNamespace(
            extract_products_with_stats=MagicMock(return_value=extraction)
        )
        transform_module = SimpleNamespace(
            transform_products=MagicMock(return_value=pd.DataFrame())
        )

        with (
            patch.object(retailer_etl, "initiate_scrape_run", return_value=99),
            patch.object(retailer_etl, "fail_scrape_run") as fail_run,
            patch.object(
                retailer_etl,
                "import_module",
                side_effect=[extract_module, transform_module],
            ),
            patch.object(
                retailer_etl, "_connect", return_value=connection_context
            ) as connect,
        ):
            try:
                retailer_etl.run_retailer_etl(
                    42, "morrisons", "https://groceries.morrisons.com"
                )
            except ValueError as error:
                assert "No valid morrisons products" in str(error)
            else:
                raise AssertionError(
                    "Expected an error for an all-invalid batch")

        connect.assert_not_called()
        fail_run.assert_called_once_with(
            99, "No valid morrisons products to load for this batch"
        )


class TestMain:
    def test_passes_arguments_and_prints_load_summary(self, capsys) -> None:
        result = LoadResult(10, 2, 3, 1)
        retailer_url = "https://groceries.morrisons.com"

        with patch.object(
            retailer_etl, "run_retailer_etl", return_value=result
        ) as run_etl:
            exit_code = retailer_etl.main([
                "--batch-id", "42",
                "--retailer-name", "Morrisons",
                "--retailer-url", retailer_url,
            ])

        run_etl.assert_called_once_with(42, "Morrisons", retailer_url)
        assert exit_code == 0
        assert capsys.readouterr().out.splitlines() == [
            "Batch 42: loaded 10 snapshots.",
            "New brands: 2",
            "New canonical products: 3",
            "New retailer categories: 1",
        ]
