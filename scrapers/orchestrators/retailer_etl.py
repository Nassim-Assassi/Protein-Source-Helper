"""Run a retailer extract-transform-load pipeline for an existing batch."""

import argparse
from importlib import import_module
from time import perf_counter

from scrapers.config import Config
from scrapers.loader.load import LoadResult, _connect, load_scrape
from scrapers.logger_setup import logger
from scrapers.orchestrators.scrape_run_helpers import (
    fail_scrape_run,
    initiate_scrape_run,
)
from scrapers.retailer_config import RetailerConfig


def _format_duration(seconds: float) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    if minutes:
        return f"{int(minutes)}m {remaining_seconds:.1f}s"
    return f"{remaining_seconds:.1f}s"


def _mark_scrape_run_failed(scrape_run_id: int, error: Exception) -> None:
    try:
        fail_scrape_run(scrape_run_id, str(error))
    except Exception:
        logger.exception("Failed to mark scrape run %s as failed.",
                         scrape_run_id)


def run_retailer_etl(
    scrape_batch_id: int, retailer_name: str, retailer_url: str
) -> LoadResult:
    """Extract, transform, and load products for a retailer and batch."""
    retailer = RetailerConfig(name=retailer_name, url=retailer_url)
    scrape_run_id = initiate_scrape_run(scrape_batch_id, retailer)
    extract_module = f"scrapers.{retailer_name}_scraper.extract"
    transform_module = f"scrapers.{retailer_name}_scraper.transform"
    try:
        extract_products_with_stats = import_module(
            extract_module
        ).extract_products_with_stats
        transform_products = import_module(
            transform_module
        ).transform_products
    except ModuleNotFoundError as error:
        if error.name not in {
            f"scrapers.{retailer_name}_scraper",
            extract_module,
            transform_module,
        }:
            _mark_scrape_run_failed(scrape_run_id, error)
            raise
        missing_module_error = ValueError(
            f"No scraper modules found for {retailer_name!r}"
        )
        _mark_scrape_run_failed(scrape_run_id, missing_module_error)
        raise missing_module_error from error
    except Exception as error:
        _mark_scrape_run_failed(scrape_run_id, error)
        raise

    try:
        logger.info("Starting extract module for %s, batch %s.",
                    retailer_name, scrape_batch_id)
        started_at = perf_counter()
        extraction = extract_products_with_stats()
        logger.info(
            "Extraction finished in %s: %d products extracted, %d failed out of "
            "%d discovered.",
            _format_duration(perf_counter() - started_at),
            len(extraction.products),
            extraction.failed_count,
            extraction.discovered_count,
        )

        logger.info("Starting transform module for %s, batch %s.",
                    retailer_name, scrape_batch_id)
        started_at = perf_counter()
        products = transform_products(extraction.products)
        skipped_count = len(extraction.products) - len(products)
        logger.info(
            "Transformation finished in %s: %d products ready to load, %d rows "
            "skipped.",
            _format_duration(perf_counter() - started_at),
            len(products),
            skipped_count,
        )
        if products.empty:
            raise ValueError(
                f"No valid {retailer_name} products to load for this batch"
            )

        logger.info("Starting load module for %s, batch %s.",
                    retailer_name, scrape_batch_id)
        started_at = perf_counter()
        with _connect(Config) as connection:
            result = load_scrape(connection, scrape_run_id, retailer, products)
        logger.info(
            "Load finished in %s: %d snapshots loaded, %d new brands, %d new "
            "canonical products, %d new categories.",
            _format_duration(perf_counter() - started_at),
            result.loaded_count,
            result.new_brand_count,
            result.new_product_count,
            result.new_retailer_category_count,
        )
        return result
    except Exception as error:
        _mark_scrape_run_failed(scrape_run_id, error)
        raise


def main(argv: list[str] | None = None) -> int:
    """Run a retailer ETL using its batch ID, name, and URL."""
    parser = argparse.ArgumentParser(
        description="Extract, transform, and load retailer product data."
    )
    parser.add_argument(
        "--batch-id",
        type=int,
        required=True,
        help="ID of the existing scrape batch to load",
    )
    parser.add_argument("--retailer-name", required=True)
    parser.add_argument("--retailer-url", required=True)
    args = parser.parse_args(argv)

    result = run_retailer_etl(
        args.batch_id, args.retailer_name, args.retailer_url
    )
    print(f"Batch {args.batch_id}: loaded {result.loaded_count} snapshots.")
    print(f"New brands: {result.new_brand_count}")
    print(f"New canonical products: {result.new_product_count}")
    print(f"New retailer categories: {result.new_retailer_category_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
