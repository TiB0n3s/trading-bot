"""Trend and market-alignment helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from indicator_state import compute_indicator_state


def compute_trend(recent_actions: list) -> dict:
    state = compute_indicator_state(
        recent_actions,
        buy_flip_min=2,
        sell_flip_min=2,
        confirmed_min=3,
    )
    return {
        "direction": state["direction"],
        "strength": state["strength"],
        "consecutive_count": state["consecutive_count"],
        "last_signal": state["last_signal"],
        "flip_event": state["flip_event"],
        "confirmed_entry": state["confirmed_entry"],
        "confirmed_exit": state["confirmed_exit"],
        "bullish_candidate": state["bullish_candidate"],
        "bearish_candidate": state["bearish_candidate"],
        "previous_opposite_count": state["previous_opposite_count"],
    }


def symbol_market_alignment(
    symbol: str,
    *,
    symbol_market_alignment_map: dict[str, dict[str, Any]],
    market_bias: dict[str, dict[str, Any]],
    trend_table: dict[str, dict[str, Any]],
    signal_history: dict[str, list[str]],
    load_market_context: Callable[[], None],
    refresh_signal_history: Callable[[str], None],
) -> dict[str, Any]:
    symbol = symbol.upper()
    mapping = symbol_market_alignment_map.get(
        symbol,
        {
            "cluster": "unknown",
            "benchmark": "SPY",
        },
    )

    cluster = mapping.get("cluster", "unknown")
    benchmark = mapping.get("benchmark", "SPY")

    load_market_context()
    if benchmark not in trend_table:
        refresh_signal_history(benchmark)
        trend_table[benchmark] = compute_trend(signal_history.get(benchmark, []))

    symbol_bias_entry = market_bias.get(symbol) or {}
    benchmark_bias_entry = market_bias.get(benchmark) or {}
    benchmark_trend = trend_table.get(benchmark) or {}

    symbol_bias = symbol_bias_entry.get("bias")
    benchmark_bias = benchmark_bias_entry.get("bias")
    benchmark_direction = benchmark_trend.get("direction")
    benchmark_strength = benchmark_trend.get("strength")

    aligned = True
    reasons = []

    if symbol_bias == "avoid":
        aligned = False
        reasons.append(f"{symbol} market_bias is avoid")

    if benchmark_bias == "avoid":
        aligned = False
        reasons.append(f"benchmark {benchmark} market_bias is avoid")

    if benchmark_direction == "bearish":
        aligned = False
        reasons.append(f"benchmark {benchmark} trend is bearish")

    if benchmark_direction == "neutral" and benchmark_strength == "weak":
        reasons.append(f"benchmark {benchmark} trend is neutral/weak")

    if aligned and not reasons:
        reasons.append(
            f"benchmark {benchmark} trend is {benchmark_direction}/{benchmark_strength} "
            f"and symbol bias is {symbol_bias}"
        )

    return {
        "cluster": cluster,
        "benchmark": benchmark,
        "benchmark_trend": {
            "direction": benchmark_direction,
            "strength": benchmark_strength,
            "consecutive_count": benchmark_trend.get("consecutive_count"),
        },
        "benchmark_bias": benchmark_bias,
        "symbol_bias": symbol_bias,
        "symbol_risk_level": symbol_bias_entry.get("risk_level"),
        "symbol_entry_quality": symbol_bias_entry.get("entry_quality"),
        "aligned_for_buy": aligned,
        "reason": "; ".join(reasons),
    }


def update_signal_trend_history(
    *,
    symbol: str,
    action: str,
    signal_history: dict[str, list[str]],
    trend_table: dict[str, dict[str, Any]],
    refresh_signal_history: Callable[[str], None],
    now: Callable[[], datetime],
    compute_trend_func: Callable[[list], dict[str, Any]] = compute_trend,
    log: Any = None,
) -> dict[str, Any]:
    """Refresh and append the incoming signal to the in-memory trend table."""
    now_ts = now().strftime("%Y-%m-%d %H:%M:%S")
    refresh_signal_history(symbol)
    signal_history.setdefault(symbol, []).insert(0, action)
    signal_history[symbol] = signal_history[symbol][:10]
    trend_table[symbol] = {
        **compute_trend_func(signal_history[symbol]),
        "last_time": now_ts,
    }
    if log:
        log.debug(
            f"Trend history update for {symbol}: history={signal_history[symbol]} "
            f"trend={trend_table[symbol]}"
        )
    return trend_table[symbol]
