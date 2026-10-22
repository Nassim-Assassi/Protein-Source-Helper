"""Create and fail scrape runs independently from product loading."""

from scrapers.config import Config
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


def fail_scrape_run(scrape_run_id: int, error_message: str) -> None:
    """Mark an initiated scrape run as failed."""
    with _connect(Config) as connection:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                """
				UPDATE public.scrape_run
				SET scrape_run_status = 'failed',
					scrape_run_finished_at = clock_timestamp(),
					scrape_run_error_message = %s
				WHERE scrape_run_id = %s AND scrape_run_status = 'running'
				""",
                (error_message, scrape_run_id),
            )
