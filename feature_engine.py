#!/usr/bin/env python3
from __future__ import annotations

from typing import Iterable, Sequence


def safe_pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100.0, 6)


def latest_price(closes: Sequence[float]) -> float | None:
    if not closes:
        return None
    return float(closes[-1])


def return_over_bars(closes: Sequence[float], bars_back: int) -> float | None:
    if len(closes) <= bars_back:
        return None
    current = float(closes[-1])
    previous = float(closes[-(bars_back + 1)])
    return safe_pct_change(current, previous)


def range_position(closes: Sequence[float], lookback: int) -> float | None:
    if len(closes) < lookback:
        return None

    window = [float(x) for x in closes[-lookback:]]
    low = min(window)
    high = max(window)
    current = window[-1]

    if high == low:
        return 0.5

    return round((current - low) / (high - low), 6)


def distance_from_high(closes: Sequence[float], lookback: int) -> float | None:
    if len(closes) < lookback:
        return None

    window = [float(x) for x in closes[-lookback:]]
    current = window[-1]
    high = max(window)

    if high == 0:
        return None

    return round(((current - high) / high) * 100.0, 6)


def distance_from_low(closes: Sequence[float], lookback: int) -> float | None:
    if len(closes) < lookback:
        return None

    window = [float(x) for x in closes[-lookback:]]
    current = window[-1]
    low = min(window)

    if low == 0:
        return None

    return round(((current - low) / low) * 100.0, 6)


def rolling_vwap(closes: Sequence[float], volumes: Sequence[float], lookback: int) -> float | None:
    if len(closes) < lookback or len(volumes) < lookback:
        return None

    price_window = [float(x) for x in closes[-lookback:]]
    volume_window = [float(x) for x in volumes[-lookback:]]

    total_volume = sum(volume_window)
    if total_volume <= 0:
        return None

    total_pv = sum(price * volume for price, volume in zip(price_window, volume_window))
    return round(total_pv / total_volume, 6)


def distance_from_vwap(closes: Sequence[float], volumes: Sequence[float], lookback: int) -> float | None:
    if not closes:
        return None

    current = float(closes[-1])
    vwap = rolling_vwap(closes, volumes, lookback)

    if vwap is None or vwap == 0:
        return None

    return round(((current - vwap) / vwap) * 100.0, 6)


def volume_ratio(volumes: Sequence[float], short_lookback: int, long_lookback: int) -> float | None:
    if len(volumes) < long_lookback:
        return None
    if short_lookback <= 0 or long_lookback <= 0 or short_lookback > long_lookback:
        return None

    short_window = [float(x) for x in volumes[-short_lookback:]]
    long_window = [float(x) for x in volumes[-long_lookback:]]

    short_avg = sum(short_window) / len(short_window)
    long_avg = sum(long_window) / len(long_window)

    if long_avg == 0:
        return None

    return round(short_avg / long_avg, 6)


def relative_strength(symbol_return_pct: float | None, benchmark_return_pct: float | None) -> float | None:
    if symbol_return_pct is None or benchmark_return_pct is None:
        return None
    return round(symbol_return_pct - benchmark_return_pct, 6)


def compute_feature_snapshot(
    *,
    symbol: str,
    benchmark_symbol: str,
    closes: Sequence[float],
    volumes: Sequence[float],
    benchmark_closes: Sequence[float],
    market_session: str,
    macro_regime: str | None,
    market_bias: str | None,
    trend_direction: str | None,
    trend_strength: str | None,
) -> dict:
    last = latest_price(closes)
    ret_1m = return_over_bars(closes, 1)
    ret_5m = return_over_bars(closes, 5)
    ret_15m = return_over_bars(closes, 15)
    benchmark_ret_5m = return_over_bars(benchmark_closes, 5)

    return {
        "symbol": symbol,
        "benchmark_symbol": benchmark_symbol,
        "last_price": last,
        "ret_1m": ret_1m,
        "ret_5m": ret_5m,
        "ret_15m": ret_15m,
        "range_pos_15m": range_position(closes, 15),
        "distance_from_5m_high": distance_from_high(closes, 5),
        "distance_from_5m_low": distance_from_low(closes, 5),
        "distance_from_vwap": distance_from_vwap(closes, volumes, 15),
        "volume_ratio_5m": volume_ratio(volumes, 5, 15),
        "benchmark_ret_5m": benchmark_ret_5m,
        "relative_strength_5m": relative_strength(ret_5m, benchmark_ret_5m),
        "market_session": market_session,
        "macro_regime": macro_regime,
        "market_bias": market_bias,
        "trend_direction": trend_direction,
        "trend_strength": trend_strength,
    }