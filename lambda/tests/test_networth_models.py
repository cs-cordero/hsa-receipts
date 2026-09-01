"""Tests for net-worth enum and validation helpers."""

import pytest

from corderohq.networth.models import (
    AccountType,
    AssetClass,
    account_type_meta,
    resolve_account_type_fields,
    validate_account_type,
    validate_asset_class,
    validate_birth_year_month,
    validate_loan_terms,
    validate_owners,
)


class TestEnumValues:
    def test_account_type_covers_design_values(self) -> None:
        values = {t.value for t in AccountType}
        assert values == {
            "checking",
            "savings",
            "brokerage",
            "401k",
            "roth_ira",
            "traditional_ira",
            "hsa",
            "529",
            "530a",
            "real_estate",
            "mortgage",
            "vehicle",
            "other_asset",
            "other_liability",
        }

    def test_asset_class_covers_design_values(self) -> None:
        values = {c.value for c in AssetClass}
        assert values == {
            "cash",
            "us_equity",
            "intl_equity",
            "bonds",
            "real_estate",
            "other",
        }

    def test_numeric_valued_members_are_addressable(self) -> None:
        # The digit-leading values need identifier-safe member names.
        assert AccountType.RETIREMENT_401K == "401k"
        assert AccountType.PLAN_529 == "529"


class TestValidateAccountType:
    def test_accepts_valid_value(self) -> None:
        assert validate_account_type("401k") == "401k"

    @pytest.mark.parametrize("bad", ["Checking", "ira", "", None, 401, "roth"])
    def test_rejects_invalid_value(self, bad: object) -> None:
        with pytest.raises(ValueError, match="Invalid accountType"):
            validate_account_type(bad)


class TestValidateAssetClass:
    def test_accepts_valid_value(self) -> None:
        assert validate_asset_class("us_equity") == "us_equity"

    @pytest.mark.parametrize("bad", ["Equity", "stocks", "", None, 1])
    def test_rejects_invalid_value(self, bad: object) -> None:
        with pytest.raises(ValueError, match="Invalid assetClass"):
            validate_asset_class(bad)


class TestValidateOwners:
    def test_accepts_single_owner(self) -> None:
        assert validate_owners(["p1"]) == ["p1"]

    def test_accepts_multiple_owners(self) -> None:
        assert validate_owners(["p1", "p2"]) == ["p1", "p2"]

    def test_dedupes_preserving_order(self) -> None:
        assert validate_owners(["p2", "p1", "p2"]) == ["p2", "p1"]

    @pytest.mark.parametrize("bad", [[], None, "p1", ["p1", ""], ["p1", 2], [None]])
    def test_rejects_bad_shape(self, bad: object) -> None:
        with pytest.raises(ValueError, match="owner"):
            validate_owners(bad)


class TestAccountTypeMeta:
    def test_every_account_type_has_meta(self) -> None:
        # account_type_meta must resolve for every enum member (no gaps in the map).
        for t in AccountType:
            assert account_type_meta(t.value) is not None

    def test_liability_types(self) -> None:
        assert account_type_meta("mortgage").liability is True
        assert account_type_meta("other_liability").liability is True
        assert account_type_meta("checking").liability is False
        assert account_type_meta("brokerage").liability is False

    def test_amortizing_only_on_debt_types(self) -> None:
        assert account_type_meta("mortgage").amortizing is True
        assert account_type_meta("other_liability").amortizing is True
        assert account_type_meta("checking").amortizing is False


class TestResolveAccountTypeFields:
    def test_derives_liability_and_forces_fixed_asset_class(self) -> None:
        # Even if the client claims us_equity, a mortgage's asset class is forced.
        account_type, liability, asset_class, loan_terms = resolve_account_type_fields("mortgage", "us_equity", None)
        assert account_type == "mortgage"
        assert liability is True
        assert asset_class == "other"
        assert loan_terms is None

    def test_cash_type_ignores_client_asset_class(self) -> None:
        _, liability, asset_class, _ = resolve_account_type_fields("checking", "us_equity", None)
        assert liability is False
        assert asset_class == "cash"

    def test_choose_type_validates_asset_class(self) -> None:
        _, liability, asset_class, _ = resolve_account_type_fields("brokerage", "us_equity", None)
        assert liability is False
        assert asset_class == "us_equity"

    def test_choose_type_rejects_bad_asset_class(self) -> None:
        with pytest.raises(ValueError, match="Invalid assetClass"):
            resolve_account_type_fields("brokerage", "stonks", None)

    def test_loan_terms_rejected_on_non_amortizing_type(self) -> None:
        terms = {"interestRate": 0.04, "monthlyPayment": 1, "payoffYearMonth": "2030-01"}
        with pytest.raises(ValueError, match="only allowed on amortizing"):
            resolve_account_type_fields("brokerage", "us_equity", terms)

    def test_loan_terms_allowed_on_amortizing_type(self) -> None:
        terms = {"interestRate": 0.04, "monthlyPayment": 1_000_000, "payoffYearMonth": "2030-01"}
        _, _, _, normalized = resolve_account_type_fields("other_liability", None, terms)
        assert normalized == terms


class TestValidateBirthYearMonth:
    def test_accepts_year_month(self) -> None:
        assert validate_birth_year_month("1985-07") == "1985-07"

    @pytest.mark.parametrize("bad", ["1985-7", "1985", "1985-07-01", "", None, 198507])
    def test_rejects_bad_format(self, bad: object) -> None:
        with pytest.raises(ValueError, match="birthYearMonth"):
            validate_birth_year_month(bad)


class TestValidateLoanTerms:
    def _valid(self) -> dict[str, object]:
        return {"interestRate": 0.04875, "monthlyPayment": 2_500_000_000, "payoffYearMonth": "2045-06"}

    def test_none_is_allowed_and_returns_none(self) -> None:
        assert validate_loan_terms(None, amortizing=True) is None
        assert validate_loan_terms(None, amortizing=False) is None

    def test_valid_terms_round_trip(self) -> None:
        result = validate_loan_terms(self._valid(), amortizing=True)
        assert result == self._valid()

    def test_rejected_on_non_amortizing(self) -> None:
        with pytest.raises(ValueError, match="only allowed on amortizing"):
            validate_loan_terms(self._valid(), amortizing=False)

    def test_requires_all_three_fields(self) -> None:
        terms = self._valid()
        del terms["payoffYearMonth"]
        with pytest.raises(ValueError, match="requires all of"):
            validate_loan_terms(terms, amortizing=True)

    def test_rejects_unexpected_fields(self) -> None:
        terms = self._valid()
        terms["extra"] = 1
        with pytest.raises(ValueError, match="unexpected fields"):
            validate_loan_terms(terms, amortizing=True)

    @pytest.mark.parametrize("rate", [-0.01, 1.0, 1.5, "0.05", True])
    def test_rejects_bad_interest_rate(self, rate: object) -> None:
        terms = self._valid()
        terms["interestRate"] = rate
        with pytest.raises(ValueError, match="interestRate"):
            validate_loan_terms(terms, amortizing=True)

    @pytest.mark.parametrize("payment", [-1, 2500.5, "2500", True])
    def test_rejects_bad_monthly_payment(self, payment: object) -> None:
        terms = self._valid()
        terms["monthlyPayment"] = payment
        with pytest.raises(ValueError, match="monthlyPayment"):
            validate_loan_terms(terms, amortizing=True)

    @pytest.mark.parametrize("payoff", ["2045", "2045-6", "not-a-date", 204506])
    def test_rejects_bad_payoff(self, payoff: object) -> None:
        terms = self._valid()
        terms["payoffYearMonth"] = payoff
        with pytest.raises(ValueError, match="payoffYearMonth"):
            validate_loan_terms(terms, amortizing=True)

    def test_zero_interest_rate_allowed(self) -> None:
        terms = self._valid()
        terms["interestRate"] = 0
        assert validate_loan_terms(terms, amortizing=True) is not None
