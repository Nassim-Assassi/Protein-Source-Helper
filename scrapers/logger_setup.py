"""Logger setup for the pipeline modules."""

import logging


def _setup_logging() -> logging.Logger:
    """Initialize scraper logging with an INFO-level console handler.

    Returns:
            logging.Logger: The configured shared scraper logger.
    """
    scraper_logger = logging.getLogger("scrapers")
    scraper_logger.setLevel(logging.INFO)
    scraper_logger.propagate = False

    if not scraper_logger.handlers:
        formatter = logging.Formatter(
            "{asctime} - {levelname} - {message}",
            style="{",
            datefmt="%Y-%m-%d %H:%M",
        )
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        scraper_logger.addHandler(console_handler)

    return scraper_logger


# Initialize logger once at module level for all modules to share
logger = _setup_logging()
