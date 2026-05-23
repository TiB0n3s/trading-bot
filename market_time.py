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

from datetime import datetime, date
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
