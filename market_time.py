#!/usr/bin/env python3
"""
Shared market-time helpers.

All trading-session logic should use America/New_York rather than fixed UTC
offsets so daylight saving time is handled correctly.

The bot's allowed trading window is intentionally narrower than the full
regular session:
- Weekdays only
- Not on known U.S. equity market holidays
- 9:45 AM through 3:45 PM Eastern
"""

from datetime import datetime, date, timedelta, date
import pytz

ET = pytz.timezone("America/New_York")

# U.S. equity market full-day holidays relevant to the 2026 trading year.
# Keep this explicit and conservative. Add future years before year-end.
US_EQUITY_MARKET_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # Martin Luther King Jr. Day
    date(2026, 2, 16),  # Washington's Birthday / Presidents Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day observed
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving Day
    date(2026, 12, 25), # Christmas Day
}

MARKET_OPEN_MINUTES = 9 * 60 + 45
MARKET_CLOSE_MINUTES = 15 * 60 + 45


def now_et() -> datetime:
    """Return the current timezone-aware New York time."""
    return datetime.now(ET)


def is_market_holiday(now: datetime | None = None) -> bool:
    """Return True when the date is a known U.S. equity market full-day holiday."""
    now = now or now_et()

    if now.tzinfo is None:
        now = ET.localize(now)
    else:
        now = now.astimezone(ET)

    if now.year == 2026:
        return now.date() in US_EQUITY_MARKET_HOLIDAYS_2026

    # Fail closed for unsupported future years until the holiday calendar is updated.
    return False


def is_market_hours(now: datetime | None = None) -> bool:
    """
    Return True during the bot's allowed regular trading window.

    Bot trading window:
    - Weekdays only
    - Not on known U.S. equity market holidays
    - 9:45 AM through 3:45 PM Eastern
    """
    now = now or now_et()

    if now.tzinfo is None:
        now = ET.localize(now)
    else:
        now = now.astimezone(ET)

    if now.weekday() >= 5:
        return False

    if is_market_holiday(now):
        return False

    minutes = now.hour * 60 + now.minute
    return MARKET_OPEN_MINUTES <= minutes < MARKET_CLOSE_MINUTES


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

    if is_market_holiday(now):
        return "closed_holiday"

    minutes = now.hour * 60 + now.minute

    if minutes < 4 * 60:
        return "closed"
    if minutes < 9 * 60 + 30:
        return "pre-market"
    if minutes < MARKET_OPEN_MINUTES:
        return "regular_session_pre_bot_window"
    if minutes < MARKET_CLOSE_MINUTES:
        return "open"
    if minutes < 16 * 60:
        return "regular_session_post_bot_window"
    if minutes < 20 * 60:
        return "after-hours"
    return "closed"


def observed_fixed_holiday(year: int, month: int, day: int) -> date:
    """Return the observed weekday date for a fixed-date US market holiday."""
    d = date(year, month, day)

    # If holiday falls Saturday, markets usually observe Friday.
    if d.weekday() == 5:
        return d - timedelta(days=1)

    # If holiday falls Sunday, markets usually observe Monday.
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
    """Return common NYSE full-day market holidays for a year.

    This covers the regular full-close calendar used by the bot's cron date
    targeting. It intentionally does not model early closes.
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
    """Return True if date is a common NYSE full-day market holiday."""
    holidays = set()

    # Include neighboring years for observed New Year's edge cases.
    for y in (d.year - 1, d.year, d.year + 1):
        holidays.update(market_holidays(y))

    return d in holidays


def is_trading_day(d: date) -> bool:
    """Return True for regular US market weekdays excluding full-day holidays."""
    return d.weekday() < 5 and not is_market_holiday(d)


def next_trading_date(from_date: date | None = None) -> date:
    """Return the next regular trading date after from_date."""
    d = (from_date or now_et().date()) + timedelta(days=1)

    while not is_trading_day(d):
        d += timedelta(days=1)

    return d
