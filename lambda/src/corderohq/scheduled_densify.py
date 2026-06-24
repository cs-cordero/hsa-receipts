"""Scheduled-invocation Lambda for monthly budget densification.

Invoked by an EventBridge Scheduler at midnight ET on the 1st of every month.
Runs the same `densify` routine that the API handlers use for lazy hydration,
so the cron and the on-demand path share one source of truth. See
docs/personal-finance-architecture.md "Densification" for the eager + lazy split.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from corderohq.aws.dynamodb import BudgetTable, CategoryTable, current_year_month
from corderohq.budget.densify import densify
from corderohq.util import get_env_var

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

_CATEGORY_TABLE = CategoryTable(get_env_var("CATEGORY_TABLE_NAME"))
_BUDGET_TABLE = BudgetTable(get_env_var("BUDGET_TABLE_NAME"))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run densification for the current year-month.

    Logs a single structured JSON line so "last successful densification" is
    queryable from CloudWatch Insights:
        fields @timestamp, @message
        | filter event = "scheduled_densify_done"
        | sort @timestamp desc
        | limit 20
    """
    current_ym = current_year_month()
    LOGGER.info(json.dumps({"event": "scheduled_densify_start", "currentYearMonth": current_ym}))
    try:
        rows_written = densify(_BUDGET_TABLE, _CATEGORY_TABLE, current_ym)
    except Exception:
        LOGGER.exception(json.dumps({"event": "scheduled_densify_failed", "currentYearMonth": current_ym}))
        raise
    LOGGER.info(
        json.dumps(
            {
                "event": "scheduled_densify_done",
                "currentYearMonth": current_ym,
                "rowsWritten": rows_written,
            }
        )
    )
    return {"currentYearMonth": current_ym, "rowsWritten": rows_written}
