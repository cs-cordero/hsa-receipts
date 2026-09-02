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


def row_total(row: dict[str, Any]) -> Any:
    """Account total for a snapshot row = sum of its per-class `byAssetClass` values.

    Sums preserve the incoming numeric type (Decimal in prod, int in tests). An
    empty/absent map totals to 0.
    """
    return sum((row.get("byAssetClass") or {}).values(), 0)


def compute_prefill(all_rows: list[dict[str, Any]], year_month: str) -> dict[str, dict[str, dict[str, Any]]]:
    """Most recent recorded value strictly BEFORE `year_month`, per (account, class).

    Returns {accountId: {assetClass: {"value": <v>, "fromYearMonth": <ym>}}}. This
    powers the entry grid's per-class "carried from 2026-06" prefill. Only months
    earlier than the target are considered. Legacy scalar rows (no `byAssetClass`)
    can't be attributed to a class and are skipped — after the Chunk 2 migration
    there are none.
    """
    best: dict[str, dict[str, dict[str, Any]]] = {}
    for row in all_rows:
        row_ym = row["yearMonth"]
        if row_ym >= year_month:
            continue
        account_id = row["accountId"]
        by_class = row.get("byAssetClass") or {}
        acct = best.setdefault(account_id, {})
        for cls, value in by_class.items():
            current = acct.get(cls)
            if current is None or row_ym > current["fromYearMonth"]:
                acct[cls] = {"value": value, "fromYearMonth": row_ym}
    return {aid: classes for aid, classes in best.items() if classes}


def build_month_view(
    accounts: list[dict[str, Any]],
    month_rows: list[dict[str, Any]],
    prefill: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Shape the GET /networth/{YYYY-MM} rows — one entry per account, per class.

    Membership: every active account, plus any inactive account that has a recorded
    value THIS month. For each account, the classes shown are its active
    `assetClasses` UNION any class with a recorded value this month (so a class you
    stopped tracking still appears — with its value — in months where it has data,
    and stays editable). Each row:
        {accountId, note | null,
         classes: [{assetClass, value | null, prefill | null}, ...]}
    Notes are per (account, month) and never carried forward.
    """
    month_by_account = {r["accountId"]: (r.get("byAssetClass") or {}) for r in month_rows}
    month_notes = {r["accountId"]: r["note"] for r in month_rows if r.get("note")}
    rows: list[dict[str, Any]] = []
    for account in accounts:
        account_id = account["accountId"]
        this_month = month_by_account.get(account_id, {})
        if not account.get("active", False) and not this_month:
            continue

        # Active classes first (in their stored order), then any valued-this-month
        # class not already listed.
        classes_to_show: list[str] = list(account.get("assetClasses", []))
        for cls in this_month:
            if cls not in classes_to_show:
                classes_to_show.append(cls)

        acct_prefill = prefill.get(account_id, {})
        class_entries = [
            {"assetClass": cls, "value": this_month.get(cls), "prefill": acct_prefill.get(cls)}
            for cls in classes_to_show
        ]
        rows.append({"accountId": account_id, "note": month_notes.get(account_id), "classes": class_entries})
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
        values.setdefault(year_month, {})[row["accountId"]] = row_total(row)
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
