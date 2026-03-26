"""Tests for the editability state machine."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from corderohq.budget.editability import editability

_ET = ZoneInfo("America/New_York")


def _utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0, second: int = 0) -> datetime:
    """Build a UTC datetime for the given ET wall-clock time. DST-aware."""
    return datetime(year, month, day, hour, minute, second, tzinfo=_ET).astimezone(UTC)


class TestCurrentMonth:
    def test_current_month_is_editable(self) -> None:
        assert editability("2024-06", _utc(2024, 6, 15)) == "EDITABLE"

    def test_current_month_first_day(self) -> None:
        assert editability("2024-06", _utc(2024, 6, 1, 0, 0, 0)) == "EDITABLE"

    def test_current_month_last_day(self) -> None:
        assert editability("2024-06", _utc(2024, 6, 30, 23, 59, 59)) == "EDITABLE"


class TestFutureMonths:
    @pytest.mark.parametrize("months_ahead", list(range(1, 13)))
    def test_next_12_months_editable(self, months_ahead: int) -> None:
        now = _utc(2024, 6, 15)
        target_year = 2024 + (6 + months_ahead - 1) // 12
        target_month = ((6 + months_ahead - 1) % 12) + 1
        target = f"{target_year:04d}-{target_month:02d}"
        assert editability(target, now) == "EDITABLE", f"failed for {target}"

    def test_13_months_ahead_locked(self) -> None:
        # June 2024 + 13 months = July 2025
        assert editability("2025-07", _utc(2024, 6, 15)) == "LOCKED"

    def test_24_months_ahead_locked(self) -> None:
        assert editability("2026-06", _utc(2024, 6, 15)) == "LOCKED"


class TestGracePeriod:
    def test_prev_month_within_grace_is_grace(self) -> None:
        # Now is June 3, 2024 at noon ET. Grace cutoff is June 8 at midnight ET.
        assert editability("2024-05", _utc(2024, 6, 3, 12)) == "GRACE"

    def test_prev_month_at_one_second_before_cutoff_is_grace(self) -> None:
        assert editability("2024-05", _utc(2024, 6, 7, 23, 59, 59)) == "GRACE"

    def test_prev_month_at_exact_cutoff_is_locked(self) -> None:
        # 2024-06-08T00:00:00 ET — the cutoff is "strictly before" so this is LOCKED.
        assert editability("2024-05", _utc(2024, 6, 8, 0, 0, 0)) == "LOCKED"

    def test_prev_month_one_second_after_cutoff_is_locked(self) -> None:
        assert editability("2024-05", _utc(2024, 6, 8, 0, 0, 1)) == "LOCKED"

    def test_prev_month_mid_month_is_locked(self) -> None:
        assert editability("2024-05", _utc(2024, 6, 20)) == "LOCKED"

    def test_two_months_ago_is_locked_even_during_grace(self) -> None:
        # Even when June's grace period for May is active, April is locked.
        assert editability("2024-04", _utc(2024, 6, 3)) == "LOCKED"


class TestYearBoundary:
    def test_prev_year_december_in_grace_from_january(self) -> None:
        # Now is January 5, 2025. Prev month is December 2024. Grace cutoff is Jan 8.
        assert editability("2024-12", _utc(2025, 1, 5)) == "GRACE"

    def test_prev_year_december_locked_after_grace(self) -> None:
        assert editability("2024-12", _utc(2025, 1, 15)) == "LOCKED"

    def test_january_current_month_from_january(self) -> None:
        assert editability("2025-01", _utc(2025, 1, 15)) == "EDITABLE"

    def test_next_year_december_editable_from_january(self) -> None:
        # January 2025 + 11 months = December 2025
        assert editability("2025-12", _utc(2025, 1, 15)) == "EDITABLE"

    def test_next_year_january_editable_from_january(self) -> None:
        # January 2025 + 12 months = January 2026
        assert editability("2026-01", _utc(2025, 1, 15)) == "EDITABLE"

    def test_next_year_february_locked_from_january(self) -> None:
        # January 2025 + 13 months = February 2026
        assert editability("2026-02", _utc(2025, 1, 15)) == "LOCKED"

    def test_december_to_december_plus_12(self) -> None:
        # December 2024 + 12 months = December 2025
        assert editability("2025-12", _utc(2024, 12, 15)) == "EDITABLE"

    def test_december_to_january_plus_1(self) -> None:
        # December 2024 + 1 month = January 2025
        assert editability("2025-01", _utc(2024, 12, 15)) == "EDITABLE"


class TestDstBoundaries:
    """The grace cutoff is "midnight ET on day 8 of current month". Day 8 happens
    after DST start (mid-March) and after DST end (early November), so the cutoff
    uses the offset in effect *on day 8*, not the offset on day 1.
    """

    def test_april_grace_cutoff_uses_edt(self) -> None:
        # April 2024. DST is active. Midnight ET on April 8 = 04:00 UTC.
        # 03:59 UTC = 23:59 EDT April 7 → still within grace.
        cutoff_minus_one_minute_utc = datetime(2024, 4, 8, 3, 59, tzinfo=UTC)
        assert editability("2024-03", cutoff_minus_one_minute_utc) == "GRACE"
        # 04:00 UTC = 00:00 EDT April 8 → at the cutoff (LOCKED).
        at_cutoff_utc = datetime(2024, 4, 8, 4, 0, tzinfo=UTC)
        assert editability("2024-03", at_cutoff_utc) == "LOCKED"

    def test_november_grace_cutoff_uses_est(self) -> None:
        # November 2024. DST ends Nov 3, so day 8 is EST. Midnight ET on Nov 8 = 05:00 UTC.
        cutoff_minus_one_minute_utc = datetime(2024, 11, 8, 4, 59, tzinfo=UTC)
        assert editability("2024-10", cutoff_minus_one_minute_utc) == "GRACE"
        at_cutoff_utc = datetime(2024, 11, 8, 5, 0, tzinfo=UTC)
        assert editability("2024-10", at_cutoff_utc) == "LOCKED"

    def test_march_grace_cutoff_uses_est(self) -> None:
        # March 2024. DST starts March 10, so day 8 is still EST. Midnight ET on March 8 = 05:00 UTC.
        cutoff_minus_one_minute_utc = datetime(2024, 3, 8, 4, 59, tzinfo=UTC)
        assert editability("2024-02", cutoff_minus_one_minute_utc) == "GRACE"
        at_cutoff_utc = datetime(2024, 3, 8, 5, 0, tzinfo=UTC)
        assert editability("2024-02", at_cutoff_utc) == "LOCKED"


class TestFarBoundaries:
    def test_far_past_locked(self) -> None:
        assert editability("2000-01", _utc(2024, 6, 15)) == "LOCKED"

    def test_far_future_locked(self) -> None:
        assert editability("2099-12", _utc(2024, 6, 15)) == "LOCKED"


class TestInputValidation:
    def test_naive_datetime_raises(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            editability("2024-06", datetime(2024, 6, 15))

    def test_malformed_year_month_raises(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM"):
            editability("2024/06", _utc(2024, 6, 15))

    def test_too_short_year_month_raises(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM"):
            editability("24-06", _utc(2024, 6, 15))
