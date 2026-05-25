#!/usr/bin/env python3
"""Tests for market-calendar date helpers."""

from datetime import date, datetime
import sys
from pathlib import Path

import pytz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_time import ET, expected_market_context_date, is_market_hours, market_session


def et_dt(year, month, day, hour, minute):
    return ET.localize(datetime(year, month, day, hour, minute))


def test_market_hours_opens_at_930_et():
    assert is_market_hours(et_dt(2026, 5, 11, 9, 29)) is False
    assert is_market_hours(et_dt(2026, 5, 11, 9, 30)) is True


def test_market_hours_closes_at_400_et():
    assert is_market_hours(et_dt(2026, 5, 11, 15, 59)) is True
    assert is_market_hours(et_dt(2026, 5, 11, 16, 0)) is False


def test_market_hours_closed_on_weekend():
    assert is_market_hours(et_dt(2026, 5, 9, 10, 0)) is False


def test_market_session_labels():
    assert market_session(et_dt(2026, 5, 11, 3, 59)) == "closed"
    assert market_session(et_dt(2026, 5, 11, 4, 0)) == "pre-market"
    assert market_session(et_dt(2026, 5, 11, 9, 30)) == "open"
    assert market_session(et_dt(2026, 5, 11, 16, 0)) == "after-hours"
    assert market_session(et_dt(2026, 5, 11, 20, 0)) == "closed"


def test_market_time_accepts_utc_datetime_and_converts_to_et():
    utc = pytz.utc.localize(datetime(2026, 5, 11, 13, 30))
    assert is_market_hours(utc) is True


def test_market_time_handles_standard_time_offset():
    utc = pytz.utc.localize(datetime(2026, 1, 12, 14, 30))
    assert is_market_hours(utc) is True


def test_expected_market_context_date_uses_same_trading_day():
    assert expected_market_context_date(date(2026, 5, 26)) == date(2026, 5, 26)


def test_expected_market_context_date_skips_market_holiday():
    assert expected_market_context_date(date(2026, 5, 25)) == date(2026, 5, 26)


def test_expected_market_context_date_skips_weekend():
    assert expected_market_context_date(date(2026, 5, 23)) == date(2026, 5, 26)


if __name__ == "__main__":
    test_market_hours_opens_at_930_et()
    print("[OK] test_market_hours_opens_at_930_et")
    test_market_hours_closes_at_400_et()
    print("[OK] test_market_hours_closes_at_400_et")
    test_market_hours_closed_on_weekend()
    print("[OK] test_market_hours_closed_on_weekend")
    test_market_session_labels()
    print("[OK] test_market_session_labels")
    test_market_time_accepts_utc_datetime_and_converts_to_et()
    print("[OK] test_market_time_accepts_utc_datetime_and_converts_to_et")
    test_market_time_handles_standard_time_offset()
    print("[OK] test_market_time_handles_standard_time_offset")
    test_expected_market_context_date_uses_same_trading_day()
    print("[OK] test_expected_market_context_date_uses_same_trading_day")
    test_expected_market_context_date_skips_market_holiday()
    print("[OK] test_expected_market_context_date_skips_market_holiday")
    test_expected_market_context_date_skips_weekend()
    print("[OK] test_expected_market_context_date_skips_weekend")
    print("\nAll 9 market-time tests passed.")
