from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv


class Config:
    """Load database settings from a project .env or environment variables."""

    DATABASE_HOST: str
    DATABASE_PORT: str
    DATABASE_NAME: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    _REQUIRED_SETTINGS: ClassVar[tuple[str]] = (
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
    )

    @classmethod
    def load(cls) -> None:
        """Load settings from mocked values, .env, or environment variables.

        Existing class attributes are left untouched to support test mocks.
        """
        if cls._is_already_loaded():
            return

        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            cls._load_from_env(env_path)
        elif cls._env_vars_available():
            cls._load_from_env_vars()
        elif os.environ.get("PYTEST_CURRENT_TEST"):
            raise RuntimeError(
                "Database config is not set for pytest; mock Config settings "
                "or provide all DATABASE_* environment variables."
            )
        else:
            cls._load_from_env_vars()

    @classmethod
    def _is_already_loaded(cls) -> bool:
        return all(
            getattr(cls, setting, None) is not None
            for setting in cls._REQUIRED_SETTINGS
        )

    @classmethod
    def _env_vars_available(cls) -> bool:
        return all(os.environ.get(setting) for setting in cls._REQUIRED_SETTINGS)

    @classmethod
    def _load_from_env(cls, env_path: Path) -> None:
        """Load and validate the required settings from the project .env."""
        load_dotenv(dotenv_path=env_path, override=True)
        cls._load_from_env_vars()

    @classmethod
    def _load_from_env_vars(cls) -> None:
        """Load and validate settings from process environment variables."""
        missing = [
            setting
            for setting in cls._REQUIRED_SETTINGS
            if not os.environ.get(setting)
        ]
        if missing:
            raise RuntimeError(
                f"Missing required database settings: {', '.join(missing)}"
            )
        for setting in cls._REQUIRED_SETTINGS:
            setattr(cls, setting, os.environ[setting])


# Load the config when the module is imported to ensure settings are available.
Config.load()
