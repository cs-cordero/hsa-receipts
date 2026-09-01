"""Tests for the pure net-worth aggregation helpers."""

from corderohq.networth.snapshots import build_history, build_month_view, compute_prefill


def _row(year_month: str, account_id: str, value: int, note: str | None = None) -> dict[str, object]:
    row: dict[str, object] = {"yearMonth": year_month, "accountId": account_id, "value": value}
    if note is not None:
        row["note"] = note
    return row


class TestComputePrefill:
    def test_picks_most_recent_prior_value_per_account(self) -> None:
        rows = [
            _row("2026-01", "a1", 100),
            _row("2026-03", "a1", 300),
            _row("2026-02", "a2", 50),
        ]
        result = compute_prefill(rows, "2026-04")
        assert result["a1"] == {"value": 300, "fromYearMonth": "2026-03"}
        assert result["a2"] == {"value": 50, "fromYearMonth": "2026-02"}

    def test_excludes_target_month_and_future(self) -> None:
        rows = [
            _row("2026-03", "a1", 300),  # target month itself — not a prefill
            _row("2026-05", "a1", 500),  # future — ignored
            _row("2026-02", "a1", 200),  # prior — this is the prefill
        ]
        result = compute_prefill(rows, "2026-03")
        assert result["a1"] == {"value": 200, "fromYearMonth": "2026-02"}

    def test_empty_when_no_prior_rows(self) -> None:
        assert compute_prefill([_row("2026-03", "a1", 1)], "2026-01") == {}


class TestBuildMonthView:
    def _accounts(self) -> list[dict[str, object]]:
        return [
            {"accountId": "a1", "name": "Checking", "active": True, "sortOrder": 0},
            {"accountId": "a2", "name": "Old 401k", "active": False, "sortOrder": 1},
            {"accountId": "a3", "name": "Brokerage", "active": True, "sortOrder": 2},
        ]

    def test_includes_active_and_inactive_with_value(self) -> None:
        month_rows = [_row("2026-06", "a2", 900)]  # inactive account has a value this month
        prefill = {"a1": {"value": 100, "fromYearMonth": "2026-05"}}
        result = build_month_view(self._accounts(), month_rows, prefill)
        ids = [r["accountId"] for r in result]
        # a1 and a3 active; a2 inactive but has a value → included. Order preserved.
        assert ids == ["a1", "a2", "a3"]

    def test_excludes_inactive_without_value(self) -> None:
        result = build_month_view(self._accounts(), [], {})
        ids = [r["accountId"] for r in result]
        assert ids == ["a1", "a3"]

    def test_row_carries_value_and_prefill(self) -> None:
        month_rows = [_row("2026-06", "a1", 250)]
        prefill = {"a3": {"value": 5000, "fromYearMonth": "2026-05"}}
        result = build_month_view(self._accounts(), month_rows, prefill)
        by_id = {r["accountId"]: r for r in result}
        assert by_id["a1"]["value"] == 250
        assert by_id["a1"]["prefill"] is None
        assert by_id["a3"]["value"] is None
        assert by_id["a3"]["prefill"] == {"value": 5000, "fromYearMonth": "2026-05"}

    def test_row_carries_note(self) -> None:
        month_rows = [_row("2026-06", "a1", 250, note="quarterly bonus")]
        result = build_month_view(self._accounts(), month_rows, {})
        by_id = {r["accountId"]: r for r in result}
        assert by_id["a1"]["note"] == "quarterly bonus"
        assert by_id["a3"]["note"] is None  # no note → null, never a prefill


class TestBuildHistory:
    def _accounts(self) -> list[dict[str, object]]:
        return [
            {"accountId": "a1", "name": "Checking", "active": True, "liability": False, "sortOrder": 0},
            {"accountId": "a2", "name": "Mortgage", "active": True, "liability": True, "sortOrder": 1},
            {"accountId": "a3", "name": "Closed", "active": False, "liability": False, "sortOrder": 2},
        ]

    def test_totals_net_assets_minus_liabilities(self) -> None:
        rows = [
            _row("2026-05", "a1", 1000),
            _row("2026-05", "a2", 400),
            _row("2026-06", "a1", 1200),
            _row("2026-06", "a2", 390),
        ]
        history = build_history(self._accounts(), rows)
        assert history["months"] == ["2026-05", "2026-06"]
        assert history["totals"]["2026-05"] == {"assets": 1000, "liabilities": 400, "netWorth": 600}
        assert history["totals"]["2026-06"] == {"assets": 1200, "liabilities": 390, "netWorth": 810}
        assert history["values"]["2026-06"]["a1"] == 1200

    def test_included_accounts_are_active_or_have_history(self) -> None:
        # a3 is inactive; include it only if it has a recorded value.
        rows = [_row("2026-05", "a1", 1000)]
        history = build_history(self._accounts(), rows)
        ids = [a["accountId"] for a in history["accounts"]]
        assert ids == ["a1", "a2"]  # a3 inactive + no history → excluded

        rows_with_a3 = [*rows, _row("2020-01", "a3", 77)]
        history2 = build_history(self._accounts(), rows_with_a3)
        ids2 = [a["accountId"] for a in history2["accounts"]]
        assert "a3" in ids2

    def test_empty_history(self) -> None:
        history = build_history(self._accounts(), [])
        assert history["months"] == []
        assert history["values"] == {}
        assert history["notes"] == {}
        assert history["totals"] == {}
        # Active accounts still listed even with no snapshots yet.
        assert [a["accountId"] for a in history["accounts"]] == ["a1", "a2"]

    def test_excluded_accounts_kept_in_values_but_dropped_from_totals(self) -> None:
        accounts = [
            {"accountId": "a1", "name": "Checking", "active": True, "liability": False, "sortOrder": 0},
            {
                "accountId": "a4",
                "name": "Kid 529",
                "active": True,
                "liability": False,
                "sortOrder": 3,
                "excludedFromNetWorth": True,
            },
        ]
        rows = [
            _row("2026-05", "a1", 1000),
            _row("2026-05", "a4", 5000),  # tracked but excluded
        ]
        history = build_history(accounts, rows)
        # Value is still present in the grid...
        assert history["values"]["2026-05"]["a4"] == 5000
        # ...but the totals ignore it (assets = 1000, not 6000).
        assert history["totals"]["2026-05"] == {"assets": 1000, "liabilities": 0, "netWorth": 1000}

    def test_notes_only_for_cells_with_a_note(self) -> None:
        rows = [
            _row("2026-05", "a1", 1000, note="opened account"),
            _row("2026-06", "a1", 1200),  # no note
        ]
        history = build_history(self._accounts(), rows)
        assert history["notes"]["2026-05"]["a1"] == "opened account"
        assert "2026-06" not in history["notes"]  # note-less months don't appear
