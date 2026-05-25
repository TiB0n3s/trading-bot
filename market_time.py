#!/usr/bin/env python3
"""
Shared market-time helpers.

All trading-session logic should use America/New_York rather than fixed UTC
offsets so daylight saving time is handled correctly.
"""

from datetime import datetime, date, timedelta
import pytz

ET = pytz.timezone("America/New_York")


def now_et() -> datetime:
    """Return the current timezone-aware New York time."""
    return datetime.now(ET)


def is_market_hours(now: datetime | None = None) -> bool:
    """
    Return True during the bot's allowed regular trading window.

    Bot trading window:
    - Weekdays only
    - 9:30 AM through 4:00 PM Eastern
    """
    now = now or now_et()

    if now.tzinfo is None:
        now = ET.localize(now)
    else:
        now = now.astimezone(ET)

    if now.weekday() >= 5:
        return False

    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def market_session(now: datetime | None = None) -> str:
    """
    Return a human-readable market session label.

    This is for status/diagnostics only. The trading gate should use
    is_market_hours().
    """
    now = now or now_et()

    if now.tzinfo is None:
        now = ET.localize(now)
    else:
        now = now.astimezone(ET)

    if now.weekday() >= 5:
        return "closed"

    minutes = now.hour * 60 + now.minute

    if minutes < 4 * 60:
        return "closed"
    if minutes < 9 * 60 + 30:
        return "pre-market"
    if minutes < 16 * 60:
        return "open"
    if minutes < 20 * 60:
        return "after-hours"
    return "closed"


def observed_fixed_holiday(year: int, month: int, day: int) -> date:
    """Return the observed weekday date for a fixed-date US market holiday."""
    d = date(year, month, day)

    if d.weekday() == 5:
        return d - timedelta(days=1)

    if d.weekday() == 6:
        return d + timedelta(days=1)

    return d


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return nth weekday in a month. Monday=0."""
    d = date(year, month, 1)

    while d.weekday() != weekday:
        d += timedelta(days=1)

    return d + timedelta(days=7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    """Return last weekday in a month. Monday=0."""
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)

    while d.weekday() != weekday:
        d -= timedelta(days=1)

    return d


def easter_date(year: int) -> date:
    """Return Western Easter Sunday using the Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def market_holidays(year: int) -> set[date]:
    """Return common US equity market full-day holidays for a year.

    This intentionally does not model early closes.
    """
    return {
        observed_fixed_holiday(year, 1, 1),       # New Year's Day
        nth_weekday(year, 1, 0, 3),               # MLK Day
        nth_weekday(year, 2, 0, 3),               # Presidents Day
        easter_date(year) - timedelta(days=2),    # Good Friday
        last_weekday(year, 5, 0),                 # Memorial Day
        observed_fixed_holiday(year, 6, 19),      # Juneteenth
        observed_fixed_holiday(year, 7, 4),       # Independence Day
        nth_weekday(year, 9, 0, 1),               # Labor Day
        nth_weekday(year, 11, 3, 4),              # Thanksgiving
        observed_fixed_holiday(year, 12, 25),     # Christmas
    }


def is_market_holiday(d: date) -> bool:
    """Return True if date is a common US equity market full-day holiday."""
    holidays = set()
    for y in (d.year - 1, d.year, d.year + 1):
        holidays.update(market_holidays(y))
    return d in holidays


def is_trading_day(d: date) -> bool:
    """Return True for weekdays excluding full-day market holidays."""
    return d.weekday() < 5 and not is_market_holiday(d)


def next_trading_date(from_date: date | None = None) -> date:
    """Return the next regular trading date after from_date."""
    d = (from_date or now_et().date()) + timedelta(days=1)

    while not is_trading_day(d):
        d += timedelta(days=1)

    return d


def expected_market_context_date(from_date: date | None = None) -> date:
    """Return the market_context date expected for the current session.

    On trading days, the live bot should consume same-day context. On weekends
    and full-day market holidays, pre-market research may already target the
    next regular trading session.
    """
    d = from_date or now_et().date()
    if is_trading_day(d):
        return d
    return next_trading_date(d)
