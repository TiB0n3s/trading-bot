#!/usr/bin/env python3
"""
Read-only Alpaca tape helpers.

Fetches recent intraday bars and builds tape-reading context.

This module does not place orders, approve trades, reject trades, or write to DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from broker import api
from market_intelligence.intraday_state import build_intraday_state
from market_intelligence.tape_reader import classify_tape


def _bar_to_dict(bar: Any) -> dict[str, Any]:
    """Convert an Alpaca bar object into the dict shape expected by intraday_state."""
    return {
        "open": float(getattr(bar, "o", 0) or 0),
        "high": float(getattr(bar, "h", 0) or 0),
        "low": float(getattr(bar, "l", 0) or 0),
        "close": float(getattr(bar, "c", 0) or 0),
        "volume": float(getattr(bar, "v", 0) or 0),
        "timestamp": str(getattr(bar, "t", "")),
    }


def fetch_recent_bars(
    symbol: str,
    lookback_minutes: int = 90,
    timeframe: str = "1Min",
    feed: str = "iex",
) -> list[dict[str, Any]]:
    """
    Fetch recent intraday bars from Alpaca.

    Uses IEX by default because paper accounts often reject recent SIP access.
    """
    symbol = symbol.upper()
    start = (datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)).isoformat()

    bars = list(api.get_bars(symbol, timeframe, start=start, feed=feed))
    return [_bar_to_dict(b) for b in bars]


def build_tape_context(
    symbol: str,
    current_price: float | None = None,
    lookback_minutes: int = 90,
) -> dict[str, Any]:
    """
    Return intraday state plus tape classification for a symbol.

    Safe/read-only. If Alpaca data fetch fails, return an error payload instead
    of raising.
    """
    symbol = symbol.upper()

    try:
        bars = fetch_recent_bars(symbol, lookback_minutes=lookback_minutes)
        state = build_intraday_state(
            symbol=symbol,
            bars=bars,
            current_price=current_price,
        )
        classification = classify_tape(state)

        return {
            "symbol": symbol,
            "ok": True,
            "bar_count": len(bars),
            "state": state,
            "classification": classification,
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "ok": False,
            "error": str(e),
            "bar_count": 0,
            "state": None,
            "classification": None,
        }
