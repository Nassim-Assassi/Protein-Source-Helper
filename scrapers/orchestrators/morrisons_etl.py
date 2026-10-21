"""Run the Morrisons extract-transform-load pipeline for an existing batch."""

import argparse
from time import perf_counter

from scrapers.config import Config
from scrapers.loader.load import LoadResult, _connect, load_scrape
from scrapers.logger_setup import logger
from scrapers.morrisons_scraper.extract import extract_products_with_stats
from scrapers.morrisons_scraper.transform import transform_products
from scrapers.retailer_config import RetailerConfig

RETAILER = RetailerConfig(
    name="Morrisons",
    url="https://groceries.morrisons.com",
)


def _format_duration(seconds: float) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    if minutes:
        return f"{int(minutes)}m {remaining_seconds:.1f}s"
    return f"{remaining_seconds:.1f}s"


def run_morrisons_etl(scrape_batch_id: int) -> LoadResult:
    """Extract, transform, and load Morrisons products for ``scrape_batch_id``."""
    logger.info("Starting Morrisons extract module for batch %s.",
                scrape_batch_id)
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

    logger.info("Starting Morrisons transform module for batch %s.",
                scrape_batch_id)
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
        raise ValueError("No valid Morrisons products to load for this batch")

    logger.info("Starting Morrisons load module for batch %s.",
                scrape_batch_id)
    started_at = perf_counter()
    with _connect(Config) as connection:
        result = load_scrape(connection, scrape_batch_id, RETAILER, products)
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


def main(argv: list[str] | None = None) -> int:
    """Run the Morrisons ETL for the batch ID supplied on the command line."""
    parser = argparse.ArgumentParser(
        description="Extract, transform, and load Morrisons product data."
    )
    parser.add_argument(
        "--batch-id",
        type=int,
        required=True,
        help="ID of the existing scrape batch to load",
    )
    args = parser.parse_args(argv)

    result = run_morrisons_etl(args.batch_id)
    print(f"Batch {args.batch_id}: loaded {result.loaded_count} snapshots.")
    print(f"New brands: {result.new_brand_count}")
    print(f"New canonical products: {result.new_product_count}")
    print(f"New retailer categories: {result.new_retailer_category_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
