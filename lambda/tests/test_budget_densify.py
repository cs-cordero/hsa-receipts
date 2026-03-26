"""Tests for the densification + future-walkback engine."""

from unittest.mock import MagicMock

from corderohq.aws.dynamodb import BudgetTable, CategoryTable
from corderohq.budget.densify import densify, resolve_future_targets


def _make_budget_table(rows: list[dict[str, object]]) -> tuple[BudgetTable, MagicMock]:
    bt = BudgetTable.__new__(BudgetTable)
    mock = MagicMock()
    bt._table = mock
    mock.scan.return_value = {"Items": rows}
    return bt, mock


def _make_category_table(categories: list[dict[str, object]]) -> tuple[CategoryTable, MagicMock]:
    ct = CategoryTable.__new__(CategoryTable)
    mock = MagicMock()
    ct._table = mock
    mock.scan.return_value = {"Items": categories}
    return ct, mock


def _cat(category_id: str, active: bool = True) -> dict[str, object]:
    return {"categoryId": category_id, "name": f"Cat {category_id}", "active": active}


def _row(ym: str, cat: str, amount: int) -> dict[str, object]:
    return {"yearMonth": ym, "categoryId": cat, "amount": amount}


class TestDensifyColdStart:
    def test_writes_zero_for_active_categories_at_current_ym(self) -> None:
        budget, _ = _make_budget_table([])
        cats, _ = _make_category_table([_cat("a"), _cat("b"), _cat("c", active=False)])

        written = densify(budget, cats, "2026-06")

        # 2 active categories → 2 writes at $0.
        assert written == 2

    def test_noop_when_no_categories_exist_either(self) -> None:
        budget, _ = _make_budget_table([])
        cats, _ = _make_category_table([])
        assert densify(budget, cats, "2026-06") == 0


class TestDensifyWalkForward:
    def test_idempotent_when_table_already_current(self) -> None:
        budget, _ = _make_budget_table([_row("2026-06", "a", 500)])
        cats, _ = _make_category_table([_cat("a")])
        assert densify(budget, cats, "2026-06") == 0

    def test_fills_gap_between_m_last_and_current(self) -> None:
        # M_last = 2026-03, current = 2026-06. Need to fill 04, 05, 06.
        budget, mock_b = _make_budget_table([_row("2026-03", "a", 500), _row("2026-03", "b", 300)])
        cats, _ = _make_category_table([_cat("a"), _cat("b")])

        written = densify(budget, cats, "2026-06")

        # 3 months x 2 categories = 6 rows.
        assert written == 6
        assert mock_b.put_item.call_count == 6

    def test_walk_back_preserves_amount(self) -> None:
        # A had a row in 2026-03 with $500. Walk-forward to 2026-05 should write $500.
        budget, mock_b = _make_budget_table([_row("2026-03", "a", 500)])
        cats, _ = _make_category_table([_cat("a")])

        densify(budget, cats, "2026-05")

        written_amounts = [call.kwargs["Item"]["amount"] for call in mock_b.put_item.call_args_list]
        assert written_amounts == [500, 500]

    def test_walk_forward_starts_after_m_last_and_respects_pin(self) -> None:
        # 2026-05 is already dense for cat a (an explicit pin). With current_ym = 2026-06,
        # M_last = 2026-05 and walk-forward only fills 2026-06. The pin at 2026-05 must
        # not be overwritten and 2026-04 stays untouched (it was a historical hole that
        # densification can't retroactively backfill — locked months are frozen).
        rows = [_row("2026-03", "a", 500), _row("2026-05", "a", 999)]
        budget, mock_b = _make_budget_table(rows)
        cats, _ = _make_category_table([_cat("a")])

        densify(budget, cats, "2026-06")

        written_keys = [
            (call.kwargs["Item"]["yearMonth"], call.kwargs["Item"]["amount"]) for call in mock_b.put_item.call_args_list
        ]
        assert written_keys == [("2026-06", 999)]

    def test_inactive_category_skipped_in_walk_forward(self) -> None:
        # B is deactivated; densification should not write rows for it even though
        # an older row exists.
        rows = [_row("2026-03", "a", 500), _row("2026-03", "b", 300)]
        budget, mock_b = _make_budget_table(rows)
        cats, _ = _make_category_table([_cat("a"), _cat("b", active=False)])

        densify(budget, cats, "2026-05")

        written_cats = {call.kwargs["Item"]["categoryId"] for call in mock_b.put_item.call_args_list}
        assert written_cats == {"a"}


class TestResolveFutureTargets:
    def test_returns_pinned_true_when_explicit_row_exists(self) -> None:
        budget, _ = _make_budget_table([_row("2026-06", "a", 500), _row("2026-09", "a", 1234)])
        cats, _ = _make_category_table([_cat("a")])

        result = resolve_future_targets(budget, cats, "2026-09")

        assert len(result) == 1
        assert result[0]["amount"] == 1234
        assert result[0]["pinned"] is True

    def test_walk_back_returns_pinned_false(self) -> None:
        budget, _ = _make_budget_table([_row("2026-06", "a", 500)])
        cats, _ = _make_category_table([_cat("a")])

        result = resolve_future_targets(budget, cats, "2026-09")

        assert result[0]["amount"] == 500
        assert result[0]["pinned"] is False

    def test_walk_back_stops_at_first_intermediate_pin(self) -> None:
        # 2026-06=500, pin at 2026-07=777. Lookup 2026-09 should find 777, not 500.
        rows = [_row("2026-06", "a", 500), _row("2026-07", "a", 777)]
        budget, _ = _make_budget_table(rows)
        cats, _ = _make_category_table([_cat("a")])

        result = resolve_future_targets(budget, cats, "2026-09")

        assert result[0]["amount"] == 777
        assert result[0]["pinned"] is False

    def test_omits_categories_with_no_history(self) -> None:
        budget, _ = _make_budget_table([])
        cats, _ = _make_category_table([_cat("a")])

        result = resolve_future_targets(budget, cats, "2026-09")

        assert result == []

    def test_omits_inactive_categories(self) -> None:
        budget, _ = _make_budget_table([_row("2026-06", "a", 500), _row("2026-06", "b", 300)])
        cats, _ = _make_category_table([_cat("a"), _cat("b", active=False)])

        result = resolve_future_targets(budget, cats, "2026-09")

        cat_ids = {r["categoryId"] for r in result}
        assert cat_ids == {"a"}
