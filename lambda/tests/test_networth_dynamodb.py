"""Tests for ProfileTable, AccountTable, and NetWorthSnapshotTable."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from corderohq.aws.dynamodb import AccountTable, NetWorthSnapshotTable, ProfileTable


# Same split-fixture trick as test_budget_categories: share one MagicMock as
# `._table` so tests can drive `mock.scan.return_value` etc. directly.
@pytest.fixture
def mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def profile(mock: MagicMock) -> ProfileTable:
    t = ProfileTable.__new__(ProfileTable)
    t._table = mock
    return t


@pytest.fixture
def accounts(mock: MagicMock) -> AccountTable:
    t = AccountTable.__new__(AccountTable)
    t._table = mock
    return t


@pytest.fixture
def snapshots(mock: MagicMock) -> NetWorthSnapshotTable:
    t = NetWorthSnapshotTable.__new__(NetWorthSnapshotTable)
    t._table = mock
    return t


class TestProfileTable:
    def test_list_people_excludes_settings_and_sorts_by_name(self, profile: ProfileTable, mock: MagicMock) -> None:
        mock.query.return_value = {
            "Items": [
                {"householdId": "HOUSEHOLD", "personId": "01B", "name": "Zoe", "birthYearMonth": "1990-01"},
                {"householdId": "HOUSEHOLD", "personId": "SETTINGS", "horizonAge": 95},
                {"householdId": "HOUSEHOLD", "personId": "01A", "name": "adam", "birthYearMonth": "1988-03"},
            ]
        }
        result = profile.list_people()
        assert [p["name"] for p in result] == ["adam", "Zoe"]

    def test_create_person_writes_item(self, profile: ProfileTable, mock: MagicMock) -> None:
        result = profile.create_person("  Jordan  ", "1985-07")
        assert result["name"] == "Jordan"
        assert result["birthYearMonth"] == "1985-07"
        assert "personId" in result
        assert result["householdId"] == "HOUSEHOLD"
        assert "createdAt" in result and "updatedAt" in result
        mock.put_item.assert_called_once()

    def test_create_person_rejects_empty_name(self, profile: ProfileTable) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            profile.create_person("   ", "1985-07")

    def test_create_person_rejects_bad_birth_month(self, profile: ProfileTable) -> None:
        with pytest.raises(ValueError, match="birthYearMonth"):
            profile.create_person("Jordan", "July 1985")

    def test_update_person_returns_none_when_absent(self, profile: ProfileTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {}
        assert profile.update_person("nope", name="X") is None

    def test_update_person_sets_name_and_birth_month(self, profile: ProfileTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {"Item": {"householdId": "HOUSEHOLD", "personId": "p1", "name": "Old"}}
        mock.update_item.return_value = {"Attributes": {"personId": "p1", "name": "New", "birthYearMonth": "1991-02"}}
        result = profile.update_person("p1", name="New", birth_year_month="1991-02")
        assert result is not None and result["name"] == "New"
        kwargs = mock.update_item.call_args.kwargs
        assert "birthYearMonth = :bym" in kwargs["UpdateExpression"]
        assert kwargs["ExpressionAttributeNames"]["#n"] == "name"

    def test_update_person_rejects_bad_birth_month(self, profile: ProfileTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {"Item": {"personId": "p1", "name": "Old"}}
        with pytest.raises(ValueError, match="birthYearMonth"):
            profile.update_person("p1", birth_year_month="bad")


class TestAccountTableCreate:
    def test_creates_asset_account(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.scan.return_value = {"Items": []}
        result = accounts.create(
            name="Chase Checking",
            account_type="checking",
            asset_class="cash",
            owners=["p1"],
        )
        assert result["name"] == "Chase Checking"
        assert result["accountType"] == "checking"
        assert result["assetClass"] == "cash"
        # liability is derived from the type, not passed in.
        assert result["liability"] is False
        assert result["owners"] == ["p1"]
        assert result["excludedFromNetWorth"] is False  # defaults to included
        assert result["active"] is True
        assert result["sortOrder"] == 0
        assert "loanTerms" not in result and "notes" not in result
        mock.put_item.assert_called_once()

    def test_creates_excluded_account(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.scan.return_value = {"Items": []}
        result = accounts.create(
            name="Kid's 529",
            account_type="529",
            asset_class="us_equity",
            owners=["p1"],
            excluded_from_net_worth=True,
        )
        assert result["excludedFromNetWorth"] is True

    def test_mortgage_forces_liability_and_asset_class(self, accounts: AccountTable, mock: MagicMock) -> None:
        # Client claims us_equity; the type forces liability=True and assetClass=other.
        mock.scan.return_value = {"Items": [{"accountId": "a0", "name": "Other", "sortOrder": 4}]}
        loan_terms = {"interestRate": 0.045, "monthlyPayment": 2_500_000_000, "payoffYearMonth": "2045-06"}
        result = accounts.create(
            name="Mortgage",
            account_type="mortgage",
            asset_class="us_equity",
            owners=["p1", "p2"],
            loan_terms=loan_terms,
            notes="30-year fixed",
        )
        assert result["liability"] is True
        assert result["assetClass"] == "other"
        assert result["owners"] == ["p1", "p2"]
        # interestRate is stored as Decimal (DynamoDB rejects floats); the rest is unchanged.
        assert result["loanTerms"]["interestRate"] == Decimal("0.045")
        assert result["loanTerms"]["monthlyPayment"] == 2_500_000_000
        assert result["loanTerms"]["payoffYearMonth"] == "2045-06"
        assert result["notes"] == "30-year fixed"
        assert result["sortOrder"] == 5  # max existing (4) + 1

    def test_rejects_empty_owners(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.scan.return_value = {"Items": []}
        with pytest.raises(ValueError, match="owners must be a non-empty list"):
            accounts.create(name="X", account_type="checking", asset_class="cash", owners=[])

    def test_rejects_invalid_account_type(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.scan.return_value = {"Items": []}
        with pytest.raises(ValueError, match="Invalid accountType"):
            accounts.create(name="X", account_type="chequing", asset_class="cash", owners=["p1"])

    def test_rejects_loan_terms_on_non_amortizing_type(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.scan.return_value = {"Items": []}
        with pytest.raises(ValueError, match="only allowed on amortizing"):
            accounts.create(
                name="Brokerage",
                account_type="brokerage",
                asset_class="us_equity",
                owners=["p1"],
                loan_terms={"interestRate": 0.04, "monthlyPayment": 1, "payoffYearMonth": "2030-01"},
            )

    def test_rejects_duplicate_name_case_insensitive(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.scan.return_value = {"Items": [{"accountId": "a1", "name": "Chase Checking", "sortOrder": 0}]}
        with pytest.raises(ValueError, match="already exists"):
            accounts.create(name="chase checking", account_type="checking", asset_class="cash", owners=["p1"])


class TestAccountTableUpdate:
    def test_returns_none_when_absent(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {}
        assert accounts.update("nope", {"name": "X"}) is None

    def test_updates_name_and_asset_class_on_choose_type(self, accounts: AccountTable, mock: MagicMock) -> None:
        # Brokerage is a "choose" type, so its asset class is editable.
        mock.get_item.return_value = {
            "Item": {"accountId": "a1", "name": "Old", "accountType": "brokerage", "liability": False}
        }
        mock.scan.return_value = {"Items": [{"accountId": "a1", "name": "Old", "sortOrder": 0}]}
        mock.update_item.return_value = {"Attributes": {"accountId": "a1", "name": "New"}}
        accounts.update("a1", {"name": "New", "assetClass": "bonds"})
        kwargs = mock.update_item.call_args.kwargs
        expr = kwargs["UpdateExpression"]
        assert "assetClass = :ac" in expr
        assert "accountType" not in expr  # type is immutable
        assert kwargs["ExpressionAttributeNames"]["#n"] == "name"

    def test_rejects_asset_class_change_on_fixed_type(self, accounts: AccountTable, mock: MagicMock) -> None:
        # Checking fixes assetClass to cash, so an override is rejected.
        mock.get_item.return_value = {
            "Item": {"accountId": "a1", "name": "A", "accountType": "checking", "liability": False}
        }
        with pytest.raises(ValueError, match="assetClass is fixed"):
            accounts.update("a1", {"assetClass": "us_equity"})

    def test_updates_owners_wholesale(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {
            "Item": {"accountId": "a1", "name": "A", "accountType": "brokerage", "liability": False, "owners": ["p1"]}
        }
        mock.update_item.return_value = {"Attributes": {"accountId": "a1", "name": "A", "owners": ["p1", "p2"]}}
        accounts.update("a1", {"owners": ["p1", "p2"]})
        kwargs = mock.update_item.call_args.kwargs
        assert "#ow = :owners" in kwargs["UpdateExpression"]
        assert kwargs["ExpressionAttributeNames"]["#ow"] == "owners"
        assert kwargs["ExpressionAttributeValues"][":owners"] == ["p1", "p2"]

    def test_updates_excluded_from_net_worth(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {
            "Item": {"accountId": "a1", "name": "A", "accountType": "brokerage", "excludedFromNetWorth": False}
        }
        mock.update_item.return_value = {"Attributes": {"accountId": "a1", "excludedFromNetWorth": True}}
        accounts.update("a1", {"excludedFromNetWorth": True})
        kwargs = mock.update_item.call_args.kwargs
        assert "excludedFromNetWorth = :exc" in kwargs["UpdateExpression"]
        assert kwargs["ExpressionAttributeValues"][":exc"] is True

    def test_rejects_non_bool_excluded_flag(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {"Item": {"accountId": "a1", "name": "A", "accountType": "brokerage"}}
        with pytest.raises(ValueError, match="excludedFromNetWorth must be a boolean"):
            accounts.update("a1", {"excludedFromNetWorth": "yes"})

    def test_rejects_empty_owners_on_update(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {
            "Item": {"accountId": "a1", "name": "A", "accountType": "brokerage", "owners": ["p1"]}
        }
        with pytest.raises(ValueError, match="owners must be a non-empty list"):
            accounts.update("a1", {"owners": []})

    def test_loan_terms_rejected_on_non_amortizing_type(self, accounts: AccountTable, mock: MagicMock) -> None:
        # Brokerage is not amortizing, so setting loanTerms must be rejected.
        mock.get_item.return_value = {
            "Item": {"accountId": "a1", "name": "A", "accountType": "brokerage", "liability": False}
        }
        terms = {"interestRate": 0.04, "monthlyPayment": 1, "payoffYearMonth": "2030-01"}
        with pytest.raises(ValueError, match="only allowed on amortizing"):
            accounts.update("a1", {"loanTerms": terms})

    def test_rejects_duplicate_name_excluding_self(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {
            "Item": {"accountId": "a1", "name": "A", "accountType": "brokerage", "liability": False}
        }
        mock.scan.return_value = {
            "Items": [
                {"accountId": "a1", "name": "A", "sortOrder": 0},
                {"accountId": "a2", "name": "Taken", "sortOrder": 1},
            ]
        }
        with pytest.raises(ValueError, match="already exists"):
            accounts.update("a1", {"name": "taken"})


class TestAccountTableMisc:
    def test_list_active_sorts_by_sort_order_then_name(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.scan.return_value = {
            "Items": [
                {"accountId": "a2", "name": "Bravo", "sortOrder": 1, "active": True},
                {"accountId": "a1", "name": "Alpha", "sortOrder": 0, "active": True},
            ]
        }
        result = accounts.list_active()
        assert [a["name"] for a in result] == ["Alpha", "Bravo"]
        kwargs = mock.scan.call_args.kwargs
        assert kwargs["FilterExpression"] == "active = :val"

    def test_deactivate_returns_none_when_absent(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {}
        assert accounts.deactivate("nope") is None

    def test_deactivate_sets_active_false(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.get_item.return_value = {"Item": {"accountId": "a1", "name": "A"}}
        mock.update_item.return_value = {"Attributes": {"accountId": "a1", "active": False}}
        result = accounts.deactivate("a1")
        assert result is not None and result["active"] is False

    def test_reorder_writes_index_per_account(self, accounts: AccountTable, mock: MagicMock) -> None:
        accounts.reorder(["a2", "a0", "a1"])
        assert mock.update_item.call_count == 3
        first = mock.update_item.call_args_list[0].kwargs
        assert first["Key"] == {"accountId": "a2"}
        assert first["ExpressionAttributeValues"][":o"] == 0

    def test_accounts_with_owner_filters_by_person(self, accounts: AccountTable, mock: MagicMock) -> None:
        mock.scan.return_value = {
            "Items": [
                {"accountId": "a1", "name": "His 401k", "owners": ["p1"], "sortOrder": 0},
                {"accountId": "a2", "name": "Joint Checking", "owners": ["p1", "p2"], "sortOrder": 1},
                {"accountId": "a3", "name": "Her IRA", "owners": ["p2"], "sortOrder": 2},
            ]
        }
        # p1 owns a1 outright and co-owns the joint a2; both come back.
        result = accounts.accounts_with_owner("p1")
        assert result == [{"accountId": "a1", "name": "His 401k"}, {"accountId": "a2", "name": "Joint Checking"}]


class TestNetWorthSnapshotTable:
    def test_get_month_queries_partition(self, snapshots: NetWorthSnapshotTable, mock: MagicMock) -> None:
        mock.query.return_value = {"Items": [{"yearMonth": "2026-06", "accountId": "a1", "value": 100}]}
        result = snapshots.get_month("2026-06")
        assert result[0]["accountId"] == "a1"
        kwargs = mock.query.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":ym"] == "2026-06"

    def test_scan_all_paginates(self, snapshots: NetWorthSnapshotTable, mock: MagicMock) -> None:
        mock.scan.side_effect = [
            {"Items": [{"yearMonth": "2026-05", "accountId": "a1", "value": 1}], "LastEvaluatedKey": {"k": 1}},
            {"Items": [{"yearMonth": "2026-06", "accountId": "a1", "value": 2}]},
        ]
        result = snapshots.scan_all()
        assert len(result) == 2
        assert mock.scan.call_count == 2

    def test_upsert_month_puts_values_and_deletes_nulls(
        self, snapshots: NetWorthSnapshotTable, mock: MagicMock
    ) -> None:
        mock.query.return_value = {"Items": [{"yearMonth": "2026-06", "accountId": "a1", "value": 500}]}
        result = snapshots.upsert_month(
            "2026-06",
            [
                {"accountId": "a1", "value": 500},
                {"accountId": "a2", "value": None},
            ],
        )
        mock.put_item.assert_called_once()
        put_item = mock.put_item.call_args.kwargs["Item"]
        assert put_item == {
            "yearMonth": "2026-06",
            "accountId": "a1",
            "value": 500,
            "updatedAt": put_item["updatedAt"],
        }
        mock.delete_item.assert_called_once_with(Key={"yearMonth": "2026-06", "accountId": "a2"})
        # Returned state comes from the post-write query.
        assert result == [{"yearMonth": "2026-06", "accountId": "a1", "value": 500}]

    def test_delete_single(self, snapshots: NetWorthSnapshotTable, mock: MagicMock) -> None:
        snapshots.delete_single("2026-06", "a1")
        mock.delete_item.assert_called_once_with(Key={"yearMonth": "2026-06", "accountId": "a1"})

    def test_upsert_month_stores_trimmed_note(self, snapshots: NetWorthSnapshotTable, mock: MagicMock) -> None:
        mock.query.return_value = {"Items": []}
        snapshots.upsert_month("2026-06", [{"accountId": "a1", "value": 500, "note": "  bonus deposited  "}])
        put_item = mock.put_item.call_args.kwargs["Item"]
        assert put_item["note"] == "bonus deposited"

    def test_upsert_month_omits_blank_note(self, snapshots: NetWorthSnapshotTable, mock: MagicMock) -> None:
        mock.query.return_value = {"Items": []}
        snapshots.upsert_month("2026-06", [{"accountId": "a1", "value": 500, "note": "   "}])
        put_item = mock.put_item.call_args.kwargs["Item"]
        assert "note" not in put_item
