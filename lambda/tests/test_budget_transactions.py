"""Tests for TransactionsTable."""

from unittest.mock import MagicMock

import pytest

from corderohq.aws.dynamodb import TransactionsTable


# `mock` and `table` are split into two fixtures sharing the same MagicMock instance
# so tests can use `mock.query.return_value = ...` directly. Going through
# `table._table.*` would force ty to treat `_table` as the real boto3 Table type
# (which it's annotated as on TransactionsTable) and reject the mock attribute access.
@pytest.fixture
def mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def table(mock: MagicMock) -> TransactionsTable:
    tt = TransactionsTable.__new__(TransactionsTable)
    tt._table = mock
    return tt


class TestList:
    def test_returns_transactions_for_month(self, table: TransactionsTable, mock: MagicMock) -> None:
        mock.query.return_value = {
            "Items": [
                {"yearMonth": "2026-03", "sortId": "2026-03-01#abc", "description": "Coffee"},
            ]
        }
        result = table.list_for_month("2026-03")
        assert len(result) == 1
        assert result[0]["description"] == "Coffee"


class TestCreate:
    def test_creates_transaction_with_sort_id(self, table: TransactionsTable, mock: MagicMock) -> None:
        result = table.create(
            year_month="2026-03",
            transaction_date="2026-03-15",
            description="Grocery store",
            amount=50000000,
            category_id="cat1",
        )
        assert result["yearMonth"] == "2026-03"
        assert result["sortId"].startswith("2026-03-15#")
        assert result["description"] == "Grocery store"
        assert result["amount"] == 50000000
        assert "createdAt" in result
        mock.put_item.assert_called_once()

    def test_raises_on_empty_description(self, table: TransactionsTable) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            table.create("2026-03", "2026-03-15", "", 100, "cat1")


class TestUpdate:
    def test_updates_fields(self, table: TransactionsTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {
            "Item": {"yearMonth": "2026-03", "sortId": "2026-03-15#abc", "description": "Old"}
        }
        mock.update_item.return_value = {
            "Attributes": {"yearMonth": "2026-03", "sortId": "2026-03-15#abc", "description": "New"}
        }
        result = table.update("2026-03", "2026-03-15#abc", {"description": "New"})
        assert result is not None
        assert result["description"] == "New"

    def test_returns_none_when_not_found(self, table: TransactionsTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {}
        result = table.update("2026-03", "nonexistent", {"description": "New"})
        assert result is None

    def test_returns_existing_when_no_updates(self, table: TransactionsTable, mock: MagicMock) -> None:
        existing = {"yearMonth": "2026-03", "sortId": "2026-03-15#abc", "description": "Same"}
        mock.get_item.return_value = {"Item": existing}
        result = table.update("2026-03", "2026-03-15#abc", {})
        assert result == existing
        mock.update_item.assert_not_called()


class TestDelete:
    def test_deletes_existing_transaction(self, table: TransactionsTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {"Item": {"yearMonth": "2026-03", "sortId": "2026-03-15#abc"}}
        result = table.delete("2026-03", "2026-03-15#abc")
        assert result is True
        mock.delete_item.assert_called_once()

    def test_returns_false_when_not_found(self, table: TransactionsTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {}
        result = table.delete("2026-03", "nonexistent")
        assert result is False
        mock.delete_item.assert_not_called()
