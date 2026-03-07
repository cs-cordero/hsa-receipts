"""Shared utility functions."""

import os
from datetime import UTC, date, datetime


def get_env_var(name: str) -> str:
    """Get a required environment variable, raising if missing or blank."""
    value = os.environ[name]
    if not value:
        raise ValueError(f"{name} must not be blank")
    return value


def today() -> date:
    return datetime.now(tz=UTC).date()


def parse_date(date_str: str | None) -> date | None:
    if date_str is None:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC).date()
