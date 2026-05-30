#!/usr/bin/env python3
"""
Read-only Alpaca tape helpers.

Fetches recent intraday bars and builds tape-reading context.

This module does not place orders, approve trades, reject trades, or write to DB.
"""

from __future__ import annotations

from typing import Any

from market_intelligence.intraday_state import build_intraday_state
from market_intelligence.tape_reader import classify_tape
from services.market_data_service import bar_to_dict, market_data_service


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
    bars = market_data_service.get_recent_bar_dicts(
        symbol,
        lookback_minutes=lookback_minutes,
        timeframe=timeframe,
        feed=feed,
    )
    return [bar_to_dict(b) if not isinstance(b, dict) else b for b in bars]


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
