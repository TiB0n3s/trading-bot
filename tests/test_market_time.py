from datetime import datetime

import pytz

from market_time import ET, is_market_hours, market_session


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
    utc = pytz.utc.localize(datetime(2026, 5, 11, 13, 30))  # 9:30 AM ET during EDT
    assert is_market_hours(utc) is True


def test_market_time_handles_standard_time_offset():
    # January uses EST / UTC-5. 14:30 UTC is 9:30 AM ET.
    utc = pytz.utc.localize(datetime(2026, 1, 12, 14, 30))
    assert is_market_hours(utc) is True
