"""Pure aggregation helpers for net-worth snapshots (no AWS).

Kept separate from the table wrapper and the handler so the prefill and history
shaping logic is unit-testable in isolation — the same split the budget feature
uses for densify.py. Every function here takes plain rows/accounts and returns
plain data.

Money values arrive as whatever DynamoDB yielded (Decimal in prod, int in tests);
sums stay in that type and the handler's JSON encoder normalizes Decimal at the
boundary. `yearMonth` strings are YYYY-MM, so lexicographic ordering is
chronological.
"""

from __future__ import annotations

from typing import Any


def compute_prefill(all_rows: list[dict[str, Any]], year_month: str) -> dict[str, dict[str, Any]]:
    """Most recent recorded value strictly BEFORE `year_month`, per account.

    Returns {accountId: {"value": <value>, "fromYearMonth": <ym>}}. This powers the
    entry grid's "carried from 2026-06" prefill. Only months earlier than the target
    are considered — the current month's own recorded value is the actual value, not
    a prefill.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        row_ym = row["yearMonth"]
        if row_ym >= year_month:
            continue
        account_id = row["accountId"]
        current = best.get(account_id)
        if current is None or row_ym > current["fromYearMonth"]:
            best[account_id] = {"value": row["value"], "fromYearMonth": row_ym}
    return best


def build_month_view(
    accounts: list[dict[str, Any]],
    month_rows: list[dict[str, Any]],
    prefill: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Shape the GET /networth/{YYYY-MM} rows.

    Membership (design §5): every active account, plus any inactive account that has
    a recorded value THIS month (so a closed account's historical entry stays
    visible/editable). Rows come back in `accounts` order (already sorted by
    sortOrder). Each row: {accountId, value | null, prefill | null, note | null}.
    Notes are month-specific and never carried forward, so there is no note prefill.
    """
    month_values = {r["accountId"]: r["value"] for r in month_rows}
    month_notes = {r["accountId"]: r["note"] for r in month_rows if r.get("note")}
    rows: list[dict[str, Any]] = []
    for account in accounts:
        account_id = account["accountId"]
        has_value_this_month = account_id in month_values
        if not account.get("active", False) and not has_value_this_month:
            continue
        rows.append(
            {
                "accountId": account_id,
                "value": month_values.get(account_id),
                "prefill": prefill.get(account_id),
                "note": month_notes.get(account_id),
            }
        )
    return rows


def build_history(accounts: list[dict[str, Any]], all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Shape GET /networth/history — the Excel-style wide view.

    Returns:
        {
          "accounts": [<account dict>, ...],   # active accounts + any with history
          "months":   ["2019-01", ...],        # every month with at least one value
          "values":   {ym: {accountId: value}},
          "notes":    {ym: {accountId: note}}, # only cells that have a note
          "totals":   {ym: {assets, liabilities, netWorth}},
        }

    Totals classify each value by its account's `liability` flag; net worth is
    assets minus liabilities. Accounts flagged `excludedFromNetWorth` are skipped in
    the totals (their values still appear in `values`). A value whose account can't
    be found (shouldn't happen — accounts soft-close, never hard-delete) is treated
    as a non-liability asset so it is never silently dropped from the total.
    """
    account_by_id = {a["accountId"]: a for a in accounts}
    accounts_with_history = {r["accountId"] for r in all_rows}

    included_accounts = [a for a in accounts if a.get("active", False) or a["accountId"] in accounts_with_history]

    values: dict[str, dict[str, Any]] = {}
    notes: dict[str, dict[str, Any]] = {}
    months: set[str] = set()
    for row in all_rows:
        year_month = row["yearMonth"]
        months.add(year_month)
        values.setdefault(year_month, {})[row["accountId"]] = row["value"]
        if row.get("note"):
            notes.setdefault(year_month, {})[row["accountId"]] = row["note"]

    totals: dict[str, dict[str, Any]] = {}
    for year_month in months:
        assets: Any = 0
        liabilities: Any = 0
        for account_id, value in values[year_month].items():
            account = account_by_id.get(account_id)
            # Tracked-but-excluded accounts (e.g. a 529 you follow but don't own)
            # keep their recorded values in `values` but never roll into the totals.
            if account is not None and account.get("excludedFromNetWorth", False):
                continue
            if account is not None and account.get("liability", False):
                liabilities += value
            else:
                assets += value
        totals[year_month] = {
            "assets": assets,
            "liabilities": liabilities,
            "netWorth": assets - liabilities,
        }

    return {
        "accounts": included_accounts,
        "months": sorted(months),
        "values": values,
        "notes": notes,
        "totals": totals,
    }
