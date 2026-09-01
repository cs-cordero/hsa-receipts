"""Shared utility functions."""

import os
import re
from datetime import UTC, date, datetime

# Canonical YYYY-MM matcher, shared across budget/transactions/net-worth so the
# same year-month contract is validated identically everywhere. Domain-neutral, so
# it lives here rather than in any one feature module.
YEAR_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")


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
