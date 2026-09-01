"""Enums and validation helpers for the net-worth tracking feature.

The two enums are the load-bearing "eye on the future" decision from the design:
`AssetClass` is the key the eventual Monte Carlo simulation uses to select a
return distribution, and `AccountType` later drives tax/withdrawal rules. Both
live in code (not the DB) so the simulation feature can import the exact same
value space. The server validates incoming values against these enums and
rejects unknown ones with a 400.

Validation functions here are pure (no AWS) and raise ValueError on bad input,
matching the repo convention where table wrappers translate ValueError into a
400 at the handler boundary. The one thing NOT validated here is `owner`
foreign-key existence — that requires a Profile lookup and lives in the handler.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, NamedTuple

from corderohq.util import YEAR_MONTH_PATTERN

# Profile table keys. `HOUSEHOLD_PK` is the single literal partition key (one
# household in practice); `PROFILE_SETTINGS_SK` is the reserved sort-key sentinel
# for a future household-wide settings item (the simulation's horizon age). People
# SKs are ULIDs, so the sentinel never collides. Both are the authoritative
# definitions — the table wrapper imports them rather than re-declaring.
HOUSEHOLD_PK = "HOUSEHOLD"
PROFILE_SETTINGS_SK = "SETTINGS"

_LOAN_TERMS_FIELDS = ("interestRate", "monthlyPayment", "payoffYearMonth")


class AccountType(StrEnum):
    """Account types. Values are stored verbatim in `Account.accountType`.

    Member names are Python-identifier-safe; the string VALUES are the contract
    (DB storage, API payloads, and the sim's future tax/withdrawal-rule keys).
    Adding a value is a one-line change here.
    """

    CHECKING = "checking"
    SAVINGS = "savings"
    BROKERAGE = "brokerage"
    RETIREMENT_401K = "401k"
    ROTH_IRA = "roth_ira"
    TRADITIONAL_IRA = "traditional_ira"
    HSA = "hsa"
    PLAN_529 = "529"
    PLAN_530A = "530a"
    REAL_ESTATE = "real_estate"
    MORTGAGE = "mortgage"
    VEHICLE = "vehicle"
    OTHER_ASSET = "other_asset"
    OTHER_LIABILITY = "other_liability"


class AssetClass(StrEnum):
    """Asset classes. Values are stored verbatim in `Account.assetClass`.

    In the simulation feature this is the key that maps to a return distribution
    (cash ~0% real, us_equity lognormal with drift+vol, etc.), which is why it is
    a controlled enum rather than free text.
    """

    CASH = "cash"
    US_EQUITY = "us_equity"
    INTL_EQUITY = "intl_equity"
    BONDS = "bonds"
    REAL_ESTATE = "real_estate"
    OTHER = "other"


class AccountTypeMeta(NamedTuple):
    """Type-driven behavior for an account type — the authoritative rules.

    The account type is the "driver": it determines whether the account is a
    liability, whether its asset class is fixed (and to what) or user-chosen, and
    whether loan terms may be attached. Keeping this in code (not per-account
    input) is what makes "Mortgage implies liability" and "no US-equity mortgage"
    invariants rather than data the client could contradict.

    - liability: derived, never a client input.
    - fixed_asset_class: when set, the asset class is forced to this value and the
      client's choice is ignored. When None, the client picks from AssetClass.
      Liabilities pin this to `other` — a debt's own asset class is meaningless
      (the financed asset, e.g. a house, is a separate account).
    - amortizing: whether loanTerms may be attached (mortgage, other liabilities).
    """

    liability: bool
    fixed_asset_class: AssetClass | None
    amortizing: bool


_ACCOUNT_TYPE_META: dict[AccountType, AccountTypeMeta] = {
    AccountType.CHECKING: AccountTypeMeta(liability=False, fixed_asset_class=AssetClass.CASH, amortizing=False),
    AccountType.SAVINGS: AccountTypeMeta(liability=False, fixed_asset_class=AssetClass.CASH, amortizing=False),
    AccountType.BROKERAGE: AccountTypeMeta(liability=False, fixed_asset_class=None, amortizing=False),
    AccountType.RETIREMENT_401K: AccountTypeMeta(liability=False, fixed_asset_class=None, amortizing=False),
    AccountType.ROTH_IRA: AccountTypeMeta(liability=False, fixed_asset_class=None, amortizing=False),
    AccountType.TRADITIONAL_IRA: AccountTypeMeta(liability=False, fixed_asset_class=None, amortizing=False),
    AccountType.HSA: AccountTypeMeta(liability=False, fixed_asset_class=None, amortizing=False),
    AccountType.PLAN_529: AccountTypeMeta(liability=False, fixed_asset_class=None, amortizing=False),
    AccountType.PLAN_530A: AccountTypeMeta(liability=False, fixed_asset_class=None, amortizing=False),
    AccountType.REAL_ESTATE: AccountTypeMeta(
        liability=False, fixed_asset_class=AssetClass.REAL_ESTATE, amortizing=False
    ),
    AccountType.VEHICLE: AccountTypeMeta(liability=False, fixed_asset_class=AssetClass.OTHER, amortizing=False),
    AccountType.MORTGAGE: AccountTypeMeta(liability=True, fixed_asset_class=AssetClass.OTHER, amortizing=True),
    AccountType.OTHER_ASSET: AccountTypeMeta(liability=False, fixed_asset_class=None, amortizing=False),
    AccountType.OTHER_LIABILITY: AccountTypeMeta(liability=True, fixed_asset_class=AssetClass.OTHER, amortizing=True),
}


def account_type_meta(account_type: str) -> AccountTypeMeta:
    """Return the behavior metadata for a validated account type (raises on unknown)."""
    return _ACCOUNT_TYPE_META[AccountType(validate_account_type(account_type))]


def resolve_account_type_fields(
    account_type: Any, asset_class: Any, loan_terms: Any
) -> tuple[str, bool, str, dict[str, Any] | None]:
    """Authoritatively derive (accountType, liability, assetClass, loanTerms).

    `liability` comes from the type, never the client. `assetClass` is forced when
    the type fixes it (client value ignored) and otherwise validated against the
    enum. `loanTerms` is gated on the type's `amortizing` flag. Raises ValueError
    on any invalid or disallowed input; the table wrapper/handler surface that as a
    400.
    """
    account_type = validate_account_type(account_type)
    meta = _ACCOUNT_TYPE_META[AccountType(account_type)]
    if meta.fixed_asset_class is not None:
        resolved_asset_class = str(meta.fixed_asset_class)
    else:
        resolved_asset_class = validate_asset_class(asset_class)
    normalized_loan_terms = validate_loan_terms(loan_terms, amortizing=meta.amortizing)
    return account_type, meta.liability, resolved_asset_class, normalized_loan_terms


def validate_account_type(value: Any) -> str:
    """Return `value` if it is a valid AccountType string, else raise ValueError."""
    if not isinstance(value, str) or value not in _ACCOUNT_TYPE_VALUES:
        raise ValueError(f"Invalid accountType '{value}'; expected one of {sorted(_ACCOUNT_TYPE_VALUES)}")
    return value


def validate_asset_class(value: Any) -> str:
    """Return `value` if it is a valid AssetClass string, else raise ValueError."""
    if not isinstance(value, str) or value not in _ASSET_CLASS_VALUES:
        raise ValueError(f"Invalid assetClass '{value}'; expected one of {sorted(_ASSET_CLASS_VALUES)}")
    return value


def validate_loan_terms(loan_terms: Any, amortizing: bool) -> dict[str, Any] | None:
    """Validate an optional loanTerms blob, returning a normalized dict or None.

    Rules:
    - None/absent is always allowed and returns None.
    - Present but the account type is not `amortizing` → ValueError (loan terms
      only make sense on amortizing debts like a mortgage or personal loan).
    - All-or-nothing: if provided, all three fields (interestRate, monthlyPayment,
      payoffYearMonth) are required.
    - interestRate: a number in [0, 1) expressed as a decimal (0.04875 = 4.875%).
    - monthlyPayment: a non-negative integer in millionths of a dollar.
    - payoffYearMonth: a YYYY-MM string.

    The tracking feature never reads these back; they exist so the simulation can
    amortize liabilities. Validation is still strict so bad data can't silently
    land in the table.
    """
    if loan_terms is None:
        return None
    if not isinstance(loan_terms, dict):
        raise ValueError("loanTerms must be an object")
    if not amortizing:
        raise ValueError("loanTerms is only allowed on amortizing accounts (e.g. mortgage, personal loan)")

    missing = [f for f in _LOAN_TERMS_FIELDS if f not in loan_terms]
    if missing:
        raise ValueError(f"loanTerms requires all of {list(_LOAN_TERMS_FIELDS)}; missing {missing}")
    extra = [k for k in loan_terms if k not in _LOAN_TERMS_FIELDS]
    if extra:
        raise ValueError(f"loanTerms has unexpected fields {extra}; allowed {list(_LOAN_TERMS_FIELDS)}")

    interest_rate = loan_terms["interestRate"]
    # bool is a subclass of int — reject it explicitly so `True` can't pose as a rate.
    if isinstance(interest_rate, bool) or not isinstance(interest_rate, (int, float)):
        raise ValueError("loanTerms.interestRate must be a number")
    if not (0 <= interest_rate < 1):
        raise ValueError("loanTerms.interestRate must be a decimal in [0, 1), e.g. 0.04875 for 4.875%")

    monthly_payment = loan_terms["monthlyPayment"]
    if isinstance(monthly_payment, bool) or not isinstance(monthly_payment, int):
        raise ValueError("loanTerms.monthlyPayment must be an integer (millionths of a dollar)")
    if monthly_payment < 0:
        raise ValueError("loanTerms.monthlyPayment must be non-negative")

    payoff = loan_terms["payoffYearMonth"]
    if not isinstance(payoff, str) or not YEAR_MONTH_PATTERN.match(payoff):
        raise ValueError("loanTerms.payoffYearMonth must be a YYYY-MM string")

    return {
        "interestRate": interest_rate,
        "monthlyPayment": monthly_payment,
        "payoffYearMonth": payoff,
    }


def validate_owners(value: Any) -> list[str]:
    """Validate the shape of an account's `owners` list; return a normalized copy.

    An account is owned by one or more household people (a jointly-held account is
    simply two+ owners — there is no separate "joint" sentinel). Rules:
    - must be a list with at least one entry,
    - every entry a non-empty string (a personId),
    - duplicates collapsed, original order preserved.

    Foreign-key existence of each personId against the household is NOT checked
    here — that needs a Profile lookup and lives in the handler, the same split as
    the enums' value-space-vs-existence separation.
    """
    if not isinstance(value, list) or not value:
        raise ValueError("owners must be a non-empty list of personIds")
    seen: set[str] = set()
    result: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry:
            raise ValueError("each owner must be a non-empty personId string")
        if entry not in seen:
            seen.add(entry)
            result.append(entry)
    return result


def validate_birth_year_month(value: Any) -> str:
    """Return `value` if it is a YYYY-MM string, else raise ValueError."""
    if not isinstance(value, str) or not YEAR_MONTH_PATTERN.match(value):
        raise ValueError("birthYearMonth must be a YYYY-MM string")
    return value


_ACCOUNT_TYPE_VALUES = frozenset(t.value for t in AccountType)
_ASSET_CLASS_VALUES = frozenset(c.value for c in AssetClass)
