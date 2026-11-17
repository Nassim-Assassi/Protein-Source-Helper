"""Configuration for real-database integration tests."""

from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_ENV = PROJECT_ROOT / "test.env"

if TEST_ENV.exists():
    load_dotenv(TEST_ENV, override=False)
