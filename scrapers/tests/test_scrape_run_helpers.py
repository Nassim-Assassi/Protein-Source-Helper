from unittest.mock import MagicMock, patch

from scrapers.orchestrators import scrape_run_helpers
from scrapers.retailer_config import RetailerConfig


class TestInitiateScrapeRun:
    def test_creates_running_run_and_returns_id(self) -> None:
        connection = MagicMock()
        connection_context = MagicMock()
        connection_context.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (17,)
        retailer = RetailerConfig("morrisons", "https://example.com")

        with (
            patch.object(
                scrape_run_helpers, "_connect", return_value=connection_context
            ),
            patch.object(
                scrape_run_helpers, "_resolve_retailer_id", return_value=3
            ),
        ):
            run_id = scrape_run_helpers.initiate_scrape_run(42, retailer)

        assert run_id == 17
        query, parameters = cursor.execute.call_args.args
        assert "INSERT INTO public.scrape_run" in query
        assert "'running'" in query
        assert parameters == (42, 3)
        connection.transaction.assert_called_once()


class TestFailScrapeRun:
    def test_marks_run_failed_with_error_message(self) -> None:
        connection = MagicMock()
        connection_context = MagicMock()
        connection_context.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value

        with patch.object(
            scrape_run_helpers, "_connect", return_value=connection_context
        ):
            scrape_run_helpers.fail_scrape_run(17, "scraper failed")

        query, parameters = cursor.execute.call_args.args
        assert "scrape_run_status = 'failed'" in query
        assert parameters == ("scraper failed", 17)
