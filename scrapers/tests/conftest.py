"""Test configuration that avoids project secrets and database connections."""

import os
from unittest.mock import Mock

import psycopg
import pytest


def pytest_configure() -> None:
    """Provide dummy database settings before test modules are imported."""
    os.environ.update(
        {
            "DATABASE_HOST": "localhost",
            "DATABASE_PORT": "5432",
            "DATABASE_NAME": "test_db",
            "DATABASE_USER": "test_user",
            "DATABASE_PASSWORD": "test_password",
            "PYTEST_CURRENT_TEST": "1",
        }
    )


@pytest.fixture(autouse=True)
def prevent_database_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail immediately if a test attempts to open a real database connection."""
    monkeypatch.setattr(
        psycopg,
        "connect",
        Mock(side_effect=AssertionError("Tests must not connect to PostgreSQL")),
    )
