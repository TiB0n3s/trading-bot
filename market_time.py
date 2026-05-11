#!/usr/bin/env python3
"""
Shared market-time helpers.

All trading-session logic should use America/New_York rather than fixed UTC
offsets so daylight saving time is handled correctly.
"""

from datetime import datetime
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
