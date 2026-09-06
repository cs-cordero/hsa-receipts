"""Make the budget months dense, and resolve a value by a walk back.

Storage model (see docs/personal-finance-architecture.md "Carry-Forward"):

- Past months, the current month, and the grace month are **dense**: one row per
  active-at-densification-time category, plus any later explicit edits.
- Future months are **sparse**: only explicit `/pin` rows.
- Effective amounts for future months are resolved at read time by walking back
  category-by-category through the rows that do exist, with explicit pins
  taking precedence.

`densify` is the entry point invoked by every handler that needs a dense
current month before serving a request. It is idempotent and cheap when the
table is already current.
"""

from __future__ import annotations

from typing import Any

from corderohq.aws.dynamodb import BudgetTable, CategoryTable

# A safety limit on how far the walk back goes. The architecture says that the walk back
# has no fixed limit, and that it continues until it finds a row or reaches the end of the
# history. But an empty table and a request for a future month would then loop for ever.
# 240 months, which is 20 years, is far more than any household budget history.
_MAX_WALKBACK_MONTHS = 240


def prev_year_month(year_month: str) -> str:
    """Return the YYYY-MM string for the month immediately before `year_month`."""
    year, month = int(year_month[:4]), int(year_month[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def next_year_month(year_month: str) -> str:
    """Return the YYYY-MM string for the month immediately after `year_month`."""
    year, month = int(year_month[:4]), int(year_month[5:7])
    if month == 12:
        return f"{year + 1}-01"
    return f"{year}-{month + 1:02d}"


def densify(
    budget_table: BudgetTable,
    category_table: CategoryTable,
    current_ym: str,
) -> int:
    """Move the Budget table forward. Every month up to `current_ym` then becomes dense.

    Walks forward from `M_last + 1` through `current_ym` chronologically, writing
    a row per currently-active category for each month. The amount copies from the
    most recent prior row (per category) or stays absent if no prior row exists.
    Pin rows in the gap are preserved — densification fills missing cells only.

    Cold-start (table is empty): writes `amount=0` per active category at
    `current_ym` only. No prior months get materialized because there's no
    history to walk back to.

    Returns the number of rows written. Idempotent — re-runs after the table is
    current return 0 with no writes.
    """
    rows = budget_table.scan_all()
    by_key: dict[tuple[str, str], Any] = {(r["yearMonth"], r["categoryId"]): r["amount"] for r in rows}

    active_cats = [c for c in category_table.list_all() if c["active"]]

    past_months = sorted({r["yearMonth"] for r in rows if r["yearMonth"] <= current_ym})
    m_last = past_months[-1] if past_months else None

    if m_last is None:
        if not active_cats:
            return 0
        targets = [{"categoryId": c["categoryId"], "amount": 0} for c in active_cats]
        budget_table.put_targets(current_ym, targets)
        return len(targets)

    if m_last >= current_ym:
        return 0

    months_to_fill = _months_between_exclusive(m_last, current_ym)
    rows_written = 0
    for month in months_to_fill:
        for cat in active_cats:
            cat_id = cat["categoryId"]
            if (month, cat_id) in by_key:
                # A row is here already, such as a pin the user wrote before the month changed.
                continue
            amount = _walk_back_for(by_key, month, cat_id)
            by_key[(month, cat_id)] = amount
            budget_table.put_single(month, cat_id, amount)
            rows_written += 1

    return rows_written


def resolve_future_targets(
    budget_table: BudgetTable,
    category_table: CategoryTable,
    year_month: str,
) -> list[dict[str, Any]]:
    """Return the targets for a future yearMonth, found by a walk back, with the pin flags.

    For each currently-active category:
    - If an explicit pin exists at `(year_month, categoryId)`, include it with
      `pinned: True`.
    - Otherwise walk back month-by-month; the first row found is the effective
      amount with `pinned: False`.
    - If no row is ever found, the category is omitted (no target).

    Callers must ensure `year_month > current_ym` before calling.
    """
    rows = budget_table.scan_all()
    by_key: dict[tuple[str, str], Any] = {(r["yearMonth"], r["categoryId"]): r["amount"] for r in rows}

    active_cats = [c for c in category_table.list_all() if c["active"]]
    result: list[dict[str, Any]] = []
    for cat in active_cats:
        cat_id = cat["categoryId"]
        key = (year_month, cat_id)
        if key in by_key:
            result.append(
                {
                    "yearMonth": year_month,
                    "categoryId": cat_id,
                    "amount": by_key[key],
                    "pinned": True,
                }
            )
            continue
        amount = _walk_back_for(by_key, year_month, cat_id)
        if amount is not None:
            result.append(
                {
                    "yearMonth": year_month,
                    "categoryId": cat_id,
                    "amount": amount,
                    "pinned": False,
                }
            )
    return result


def walk_back_for(by_key: dict[tuple[str, str], Any], target: str, cat_id: str) -> Any:
    """Walk back from `target`, and find the most recent row for `cat_id`.

    The `by_key` dict must hold the full in-memory state to walk through (as built
    by callers from `scan_all`). Returns the amount of the nearest prior row, or
    `None` if no row exists within the safety bound.
    """
    cursor = prev_year_month(target)
    for _ in range(_MAX_WALKBACK_MONTHS):
        if (cursor, cat_id) in by_key:
            return by_key[(cursor, cat_id)]
        cursor = prev_year_month(cursor)
    return None


# An old name for the function above. Callers in this module still use it.
_walk_back_for = walk_back_for


def _months_between_exclusive(start_ym: str, end_ym: str) -> list[str]:
    """Return the months after `start_ym`, up to and including `end_ym`."""
    result: list[str] = []
    cursor = next_year_month(start_ym)
    while cursor <= end_ym:
        result.append(cursor)
        cursor = next_year_month(cursor)
    return result
