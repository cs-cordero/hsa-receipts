"""Shared utility functions."""

import os
import re
from datetime import UTC, date, datetime

# The one pattern for YYYY-MM. The budget, the transactions, and the net worth record all
# use it, so each one checks a year-month in the same way. It belongs to no single feature,
# so it lives here.
YEAR_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def get_env_var(name: str) -> str:
    """Return a necessary environment variable. Raise an error if it is absent or blank."""
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
