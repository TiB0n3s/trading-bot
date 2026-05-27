#!/usr/bin/env python3
"""
Intraday state helpers.

Pure calculation helpers for tape-reading features.

This module does not fetch market data, approve trades, reject trades, or place
orders. It accepts bar-like dictionaries and returns normalized intraday state.
"""

from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _bar_close(bar: dict[str, Any]) -> float:
    return safe_float(bar.get("close", bar.get("c")))


def _bar_high(bar: dict[str, Any]) -> float:
    return safe_float(bar.get("high", bar.get("h")))


def _bar_low(bar: dict[str, Any]) -> float:
    return safe_float(bar.get("low", bar.get("l")))


def _bar_volume(bar: dict[str, Any]) -> float:
    return safe_float(bar.get("volume", bar.get("v")))


def pct_change(start: float, end: float) -> float:
    start = safe_float(start)
    end = safe_float(end)

    if start <= 0:
        return 0.0

    return round((end - start) / start * 100.0, 4)


def window_return_pct(bars: list[dict[str, Any]], window: int) -> float | None:
    """Return close-to-close percent change over the last N bars."""
    if not bars or len(bars) < 2:
        return None

    use = bars[-window:] if len(bars) >= window else bars
    start = _bar_close(use[0])
    end = _bar_close(use[-1])

    return pct_change(start, end)


def session_high(bars: list[dict[str, Any]]) -> float | None:
    highs = [_bar_high(b) for b in bars or [] if _bar_high(b) > 0]
    return round(max(highs), 4) if highs else None


def session_low(bars: list[dict[str, Any]]) -> float | None:
    lows = [_bar_low(b) for b in bars or [] if _bar_low(b) > 0]
    return round(min(lows), 4) if lows else None


def vwap(bars: list[dict[str, Any]]) -> float | None:
    """
    Calculate simple session VWAP from bar high/low/close typical price.

    typical_price = (high + low + close) / 3
    vwap = sum(typical_price * volume) / sum(volume)
    """
    total_pv = 0.0
    total_volume = 0.0

    for b in bars or []:
        high = _bar_high(b)
        low = _bar_low(b)
        close = _bar_close(b)
        volume = _bar_volume(b)

        if high <= 0 or low <= 0 or close <= 0 or volume <= 0:
            continue

        typical = (high + low + close) / 3.0
        total_pv += typical * volume
        total_volume += volume

    if total_volume <= 0:
        return None

    return round(total_pv / total_volume, 4)


def distance_pct(price: float, reference: float | None) -> float | None:
    price = safe_float(price)
    reference = safe_float(reference) if reference is not None else 0.0

    if price <= 0 or reference <= 0:
        return None

    return round((price - reference) / reference * 100.0, 4)


def trend_label(ret_5m: float | None, ret_15m: float | None, ret_30m: float | None) -> str:
    """Return a simple tape trend label from short/mid returns."""
    vals = [v for v in [ret_5m, ret_15m, ret_30m] if v is not None]

    if not vals:
        return "unknown"

    positives = sum(1 for v in vals if v > 0.10)
    negatives = sum(1 for v in vals if v < -0.10)

    if positives >= 2:
        return "rising"
    if negatives >= 2:
        return "falling"
    return "mixed"


def build_intraday_state(
    symbol: str,
    bars: list[dict[str, Any]],
    current_price: float | None = None,
) -> dict[str, Any]:
    """
    Build normalized intraday state from bar dictionaries.

    Bars can use either Alpaca-style keys (o/h/l/c/v) or friendly keys
    (open/high/low/close/volume).
    """
    bars = bars or []

    latest_close = _bar_close(bars[-1]) if bars else 0.0
    price = safe_float(current_price, latest_close) if current_price is not None else latest_close

    ret_5m = window_return_pct(bars, 5)
    ret_15m = window_return_pct(bars, 15)
    ret_30m = window_return_pct(bars, 30)

    high = session_high(bars)
    low = session_low(bars)
    session_vwap = vwap(bars)

    return {
        "symbol": symbol.upper(),
        "bar_count": len(bars),
        "latest_bar_timestamp": bars[-1].get("timestamp") if bars else None,
        "current_price": round(price, 4) if price else None,
        "latest_close": round(latest_close, 4) if latest_close else None,
        "return_5m_pct": ret_5m,
        "return_15m_pct": ret_15m,
        "return_30m_pct": ret_30m,
        "trend_label": trend_label(ret_5m, ret_15m, ret_30m),
        "session_high": high,
        "session_low": low,
        "vwap": session_vwap,
        "distance_from_vwap_pct": distance_pct(price, session_vwap),
        "distance_from_session_high_pct": distance_pct(price, high),
        "distance_from_session_low_pct": distance_pct(price, low),
    }
