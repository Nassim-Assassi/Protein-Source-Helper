"""Create and fail scrape runs independently from product loading."""

from scrapers.config import Config
from scrapers.etl_contracts import ScrapeRunMetrics
from scrapers.loader.load import _connect, _resolve_retailer_id
from scrapers.retailer_config import RetailerConfig


def initiate_scrape_run(scrape_batch_id: int, retailer: RetailerConfig) -> int:
    """Create and commit a running scrape entry, returning its ID."""
    with _connect(Config) as connection:
        with connection.transaction(), connection.cursor() as cursor:
            retailer_id = _resolve_retailer_id(cursor, retailer)
            cursor.execute(
                """
				INSERT INTO public.scrape_run (
					scrape_batch_id, retailer_id, scrape_run_status
				)
				VALUES (%s, %s, 'running')
				RETURNING scrape_run_id
				""",
                (scrape_batch_id, retailer_id),
            )
            row = cursor.fetchone()
            if row is None or row[0] is None:
                raise RuntimeError(
                    "Failed to create scrape run for retailer batch"
                )
            return row[0]


def fail_scrape_run(
    scrape_run_id: int,
    error_message: str,
    metrics: ScrapeRunMetrics | None = None,
) -> None:
    """Mark an initiated scrape run as failed."""
    run_metrics = metrics or ScrapeRunMetrics()
    with _connect(Config) as connection:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                """
				UPDATE public.scrape_run
				SET scrape_run_status = 'failed',
					scrape_run_finished_at = clock_timestamp(),
                    scrape_run_error_message = %s,
                    scrape_run_discovered_count = %s,
                    scrape_run_extracted_count = %s,
                    scrape_run_extraction_failed_count = %s,
                    scrape_run_transformed_count = %s,
                    scrape_run_transformation_skipped_count = %s,
                    scrape_run_loaded_count = %s,
                    scrape_run_extraction_duration_seconds = %s,
                    scrape_run_transformation_duration_seconds = %s,
                    scrape_run_load_duration_seconds = %s
				WHERE scrape_run_id = %s AND scrape_run_status = 'running'
				""",
                (
                    error_message,
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
