from unittest.mock import MagicMock, patch

import pandas as pd

from scrapers.loader.load import LoadResult
from scrapers.morrisons_scraper.extract import ExtractionResult
from scrapers.orchestrators import morrisons_etl


class TestRunMorrisonsEtl:
    def test_extracts_transforms_and_loads_with_given_batch_id(self) -> None:
        raw_products = [{"listing_name": "Product"}]
        extraction = ExtractionResult(raw_products, 2, 1)
        transformed_products = pd.DataFrame([{"listing_name": "Product"}])
        result = LoadResult(1, 0, 1, 1)
        connection = MagicMock()
        connection_context = MagicMock()
        connection_context.__enter__.return_value = connection

        with (
            patch.object(
                morrisons_etl,
                "extract_products_with_stats",
                return_value=extraction,
            ) as extract,
            patch.object(
                morrisons_etl,
                "transform_products",
                return_value=transformed_products,
            ) as transform,
            patch.object(
                morrisons_etl, "_connect", return_value=connection_context
            ) as connect,
            patch.object(morrisons_etl, "load_scrape", return_value=result) as load,
        ):
            actual_result = morrisons_etl.run_morrisons_etl(42)

        extract.assert_called_once_with()
        transform.assert_called_once_with(raw_products)
        connect.assert_called_once_with(morrisons_etl.Config)
        load.assert_called_once_with(
            connection, 42, morrisons_etl.RETAILER, transformed_products
        )
        assert actual_result is result

    def test_does_not_open_database_when_all_products_are_skipped(self) -> None:
        extraction = ExtractionResult([{"listing_name": "Incomplete"}], 1, 0)
        connection = MagicMock()
        connection_context = MagicMock()
        connection_context.__enter__.return_value = connection

        with (
            patch.object(
                morrisons_etl,
                "extract_products_with_stats",
                return_value=extraction,
            ),
            patch.object(
                morrisons_etl,
                "transform_products",
                return_value=pd.DataFrame(),
            ),
            patch.object(
                morrisons_etl, "_connect", return_value=connection_context
            ) as connect,
        ):
            try:
                morrisons_etl.run_morrisons_etl(42)
            except ValueError as error:
                assert "No valid Morrisons products" in str(error)
            else:
                raise AssertionError(
                    "Expected an error for an all-invalid batch")

        connect.assert_not_called()


class TestMain:
    def test_passes_batch_id_and_prints_load_summary(self, capsys) -> None:
        result = LoadResult(10, 2, 3, 1)

        with patch.object(
            morrisons_etl, "run_morrisons_etl", return_value=result
        ) as run_etl:
            exit_code = morrisons_etl.main(["--batch-id", "42"])

        run_etl.assert_called_once_with(42)
        assert exit_code == 0
        assert capsys.readouterr().out.splitlines() == [
            "Batch 42: loaded 10 snapshots.",
            "New brands: 2",
            "New canonical products: 3",
            "New retailer categories: 1",
        ]
