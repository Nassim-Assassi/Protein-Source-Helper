"""Run a retailer extract-transform-load pipeline for an existing batch."""

import argparse
import re
from importlib import import_module
from pathlib import Path
from time import perf_counter

from scrapers.config import Config
from scrapers.etl_contracts import LoadResult
from scrapers.loader.load import _connect, load_scrape
from scrapers.logger_setup import logger
from scrapers.orchestrators.scrape_run_helpers import (
    fail_scrape_run,
    initiate_scrape_run,
)
from scrapers.retailer_config import RetailerConfig

LOCAL_TEST_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "local_development"
)


def _format_duration(seconds: float) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    if minutes:
        return f"{int(minutes)}m {remaining_seconds:.1f}s"
    return f"{remaining_seconds:.1f}s"


def _mark_scrape_run_failed(
    scrape_run_id: int | None, error: Exception
) -> None:
    if scrape_run_id is None:
        return
    try:
        fail_scrape_run(scrape_run_id, str(error))
    except Exception:
        logger.exception("Failed to mark scrape run %s as failed.",
                         scrape_run_id)


def run_retailer_etl(
    scrape_batch_id: int | None,
    retailer_name: str,
    retailer_url: str,
    local_test: bool = False,
) -> LoadResult | Path:
    """Extract and transform products, then load them or save a local CSV."""
    retailer = RetailerConfig(name=retailer_name, url=retailer_url)
    scrape_run_id = None
    if not local_test:
        if scrape_batch_id is None:
            raise ValueError(
                "A batch ID is required unless --local_test is set")
        scrape_run_id = initiate_scrape_run(scrape_batch_id, retailer)
    scraper_name = retailer_name.lower()
    extract_module = f"scrapers.{scraper_name}_scraper.extract"
    transform_module = f"scrapers.{scraper_name}_scraper.transform"
    try:
        extract_products_with_stats = import_module(
            extract_module
        ).extract_products_with_stats
        transform_products = import_module(
            transform_module
        ).transform_products
    except ModuleNotFoundError as error:
        if error.name not in {
            f"scrapers.{scraper_name}_scraper",
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
        transformation = transform_products(extraction.products)
        products = transformation.products
        logger.info(
            "Transformation finished in %s: %d products ready to load, %d rows "
            "skipped.",
            _format_duration(perf_counter() - started_at),
            len(products),
            transformation.skipped_count,
        )
        if products.empty:
            raise ValueError(
                f"No valid {retailer_name} products to load for this batch"
            )

        if local_test:
            retailer_slug = re.sub(
                r"[^a-z0-9_-]+", "_", retailer_name.lower()
            ).strip("_") or "retailer"
            output_path = (
                LOCAL_TEST_OUTPUT_DIR / f"{retailer_slug}_products.csv"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            products.to_csv(output_path, index=False)
            logger.info("Local test CSV saved to %s.", output_path)
            return output_path

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
        help="ID of the existing scrape batch to load",
    )
    parser.add_argument("--retailer-name", required=True)
    parser.add_argument("--retailer-url", required=True)
    parser.add_argument(
        "--local_test",
        action="store_true",
        help="Scrape and save transformed products to a local CSV",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Include detailed logs for skipped rows",
    )
    args = parser.parse_args(argv)
    logger.setLevel("DEBUG" if args.verbose else "INFO")

    if args.batch_id is None and not args.local_test:
        parser.error("--batch-id is required unless --local_test is set")

    result = run_retailer_etl(
        args.batch_id,
        args.retailer_name,
        args.retailer_url,
        local_test=args.local_test,
    )
    if isinstance(result, Path):
        print(f"Local test CSV saved to {result}")
        return 0

    print(f"Batch {args.batch_id}: loaded {result.loaded_count} snapshots.")
    print(f"New brands: {result.new_brand_count}")
    print(f"New canonical products: {result.new_product_count}")
    print(f"New retailer categories: {result.new_retailer_category_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
