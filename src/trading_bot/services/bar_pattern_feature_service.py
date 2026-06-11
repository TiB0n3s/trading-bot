"""Advanced per-bar feature extraction for observe-only learning."""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository

BAR_PATTERN_FEATURE_VERSION = "efi_pvt_orderflow_math_bar_pattern_v4"
BAR_PATTERN_RUNTIME_EFFECT = "observe_only_pattern_learning_no_live_authority"
MARKET_TZ = ZoneInfo("America/New_York")


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _bar_value(bar: Any, *names: str) -> Any:
    if isinstance(bar, dict):
        for name in names:
            if name in bar:
                return bar.get(name)
        return None
    for name in names:
        if hasattr(bar, name):
            return getattr(bar, name)
    return None


def _timestamp(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        # Polygon aggregate timestamps are milliseconds since epoch.
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_timestamp(value: Any) -> datetime | None:
    text = _timestamp(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MARKET_TZ)


def _session_phase(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    minute = dt.hour * 60 + dt.minute
    if minute < 9 * 60 + 30 or minute >= 16 * 60:
        return "off_hours"
    if minute < 10 * 60:
        return "opening_drive"
    if minute < 11 * 60 + 30:
        return "morning_trend"
    if minute < 14 * 60:
        return "midday_liquidity_decay"
    if minute < 15 * 60:
        return "afternoon_reprice"
    return "power_hour"


def _month_end_proximity_days(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    return calendar.monthrange(dt.year, dt.month)[1] - dt.day


def normalize_bar(bar: Any) -> dict[str, Any]:
    close = _float(_bar_value(bar, "close", "c"))
    bid_price = _float(_bar_value(bar, "bid_price", "bid", "bp"))
    ask_price = _float(_bar_value(bar, "ask_price", "ask", "ap"))
    spread_pct = _float(_bar_value(bar, "bid_ask_spread_pct", "spread_pct", "spread_percent"))
    if spread_pct is None and bid_price is not None and ask_price is not None and close:
        spread_pct = max(0.0, (ask_price - bid_price) / close * 100.0)
    return {
        "timestamp": _timestamp(_bar_value(bar, "timestamp", "t")),
        "open": _float(_bar_value(bar, "open", "o")),
        "high": _float(_bar_value(bar, "high", "h")),
        "low": _float(_bar_value(bar, "low", "l")),
        "close": close,
        "volume": _float(_bar_value(bar, "volume", "v")),
        "vwap": _float(_bar_value(bar, "vwap", "vw", "VWAP")),
        "source": _bar_value(bar, "source", "Source", "bar_source"),
        "feed": _bar_value(bar, "feed", "Feed", "bar_feed"),
        "adjusted": _bar_value(bar, "adjusted", "Adjusted", "bar_adjusted"),
        "trade_count": _float(_bar_value(bar, "trade_count", "transactions", "n")),
        "interval_start": _timestamp(
            _bar_value(
                bar, "interval_start", "IntervalStart", "bar_interval_start_ts", "timestamp", "t"
            )
        ),
        "interval_semantics": _bar_value(
            bar,
            "interval_semantics",
            "IntervalSemantics",
            "bar_interval_semantics",
        ),
        "bid_price": bid_price,
        "ask_price": ask_price,
        "bid_ask_spread_pct": spread_pct,
        "slippage_estimate_pct": _float(
            _bar_value(bar, "slippage_estimate_pct", "predicted_slippage_pct")
        ),
        "execution_cost_estimate_pct": _float(
            _bar_value(bar, "execution_cost_estimate_pct", "transaction_cost_pct")
        ),
        "liquidity_zone_label": _bar_value(
            bar,
            "liquidity_zone_label",
            "liquidity_zone",
            "stop_cluster_zone",
        ),
        "liquidity_sweep_risk": _float(_bar_value(bar, "liquidity_sweep_risk", "sweep_risk")),
    }


def _ema(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (window + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * alpha + out[-1] * (1.0 - alpha))
    return out


def _rsi_at(values: list[float], idx: int, window: int = 14) -> float | None:
    if idx < window:
        return None
    gains = []
    losses = []
    for pos in range(idx - window + 1, idx + 1):
        change = values[pos] - values[pos - 1]
        if change >= 0:
            gains.append(change)
        else:
            losses.append(abs(change))
    avg_gain = sum(gains) / window if gains else 0.0
    avg_loss = sum(losses) / window if losses else 0.0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _wilder_rsi(values: list[float], window: int = 14) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) <= window:
        return output

    gains: list[float] = []
    losses: list[float] = []
    for pos in range(1, window + 1):
        change = values[pos] - values[pos - 1]
        gains.append(max(0.0, change))
        losses.append(max(0.0, -change))

    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window

    def _calculate(avg_gain_value: float, avg_loss_value: float) -> float:
        if avg_loss_value == 0:
            return 100.0 if avg_gain_value > 0 else 50.0
        rs = avg_gain_value / avg_loss_value
        return 100.0 - (100.0 / (1.0 + rs))

    output[window] = _calculate(avg_gain, avg_loss)
    for idx in range(window + 1, len(values)):
        change = values[idx] - values[idx - 1]
        gain = max(0.0, change)
        loss = max(0.0, -change)
        avg_gain = ((avg_gain * (window - 1)) + gain) / window
        avg_loss = ((avg_loss * (window - 1)) + loss) / window
        output[idx] = _calculate(avg_gain, avg_loss)
    return output


def _webull_rsi_zone(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 70.0:
        return "overbought"
    if value <= 30.0:
        return "oversold"
    return "neutral"


def _webull_rsi_exit_signal(previous: float | None, current: float | None) -> str | None:
    if previous is None or current is None:
        return None
    if previous >= 70.0 and current < 70.0:
        return "exited_overbought"
    if previous <= 30.0 and current > 30.0:
        return "exited_oversold"
    return "none"


def _webull_rsi_bearish_divergence(
    closes: list[float],
    rsi_values: list[float | None],
    idx: int,
    *,
    window: int = 20,
) -> int:
    if idx <= 0 or idx >= len(closes) or idx >= len(rsi_values):
        return 0
    current_rsi = rsi_values[idx]
    if current_rsi is None:
        return 0
    start = max(0, idx - window)
    prior_pairs = [
        (closes[pos], rsi_values[pos]) for pos in range(start, idx) if rsi_values[pos] is not None
    ]
    if not prior_pairs:
        return 0
    prior_high_close, prior_high_rsi = max(prior_pairs, key=lambda item: item[0])
    if prior_high_rsi is None:
        return 0
    return 1 if closes[idx] > prior_high_close and current_rsi < prior_high_rsi else 0


def _zscore(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = variance**0.5
    if not std:
        return 0.0
    return (values[-1] - mean) / std


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance**0.5


def _rolling_corr(x_values: list[float], y_values: list[float]) -> float | None:
    if len(x_values) != len(y_values) or len(x_values) < 3:
        return None
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    x_diffs = [value - x_mean for value in x_values]
    y_diffs = [value - y_mean for value in y_values]
    x_var = sum(value * value for value in x_diffs)
    y_var = sum(value * value for value in y_diffs)
    denom = (x_var * y_var) ** 0.5
    if not denom:
        return 0.0
    return sum(x * y for x, y in zip(x_diffs, y_diffs)) / denom


def _pct_change(old: float | None, new: float | None) -> float | None:
    if old in (None, 0) or new is None:
        return None
    return (new - old) / old * 100.0


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * max(0.0, min(1.0, q))
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[int(pos)]
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _true_ranges(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    ranges = []
    for idx, high in enumerate(highs):
        low = lows[idx]
        if idx == 0:
            ranges.append(max(0.0, high - low))
            continue
        prev_close = closes[idx - 1]
        ranges.append(
            max(
                max(0.0, high - low),
                abs(high - prev_close),
                abs(low - prev_close),
            )
        )
    return ranges


def _fractional_weights(d: float, size: int, threshold: float = 1e-4) -> list[float]:
    weights = [1.0]
    for k in range(1, max(1, size)):
        weights.append(-weights[-1] / k * (d - k + 1.0))
    trimmed = [weight for weight in reversed(weights) if abs(weight) > threshold]
    return trimmed or [1.0]


def _fractional_diff_at(
    values: list[float],
    idx: int,
    *,
    d: float = 0.45,
    window: int = 60,
    threshold: float = 1e-4,
) -> float | None:
    start = max(0, idx + 1 - window)
    sample = values[start : idx + 1]
    if len(sample) < 8:
        return None
    weights = _fractional_weights(d, len(sample), threshold=threshold)
    sample = sample[-len(weights) :]
    if len(sample) != len(weights):
        return None
    return sum(weight * value for weight, value in zip(weights, sample))


def _trend_scan_label(
    *,
    closes: list[float],
    idx: int,
    max_bars: int,
    min_bars: int = 5,
) -> dict[str, Any]:
    future = closes[idx + 1 : idx + 1 + max_bars]
    if len(future) < min_bars:
        return {
            "trend_scan_label": None,
            "trend_scan_tstat": None,
            "trend_scan_bars": None,
            "trend_scan_return_pct": None,
            "trend_scan_reason": "insufficient_forward_bars",
        }

    best: dict[str, Any] | None = None
    for bars in range(min_bars, len(future) + 1):
        y_values = future[:bars]
        x_values = list(range(1, bars + 1))
        x_mean = sum(x_values) / bars
        y_mean = sum(y_values) / bars
        x_diffs = [value - x_mean for value in x_values]
        y_diffs = [value - y_mean for value in y_values]
        x_var = sum(value * value for value in x_diffs)
        if not x_var:
            continue
        slope = sum(x * y for x, y in zip(x_diffs, y_diffs)) / x_var
        intercept = y_mean - slope * x_mean
        residuals = [y - (intercept + slope * x) for x, y in zip(x_values, y_values)]
        if bars <= 2:
            continue
        residual_var = sum(value * value for value in residuals) / (bars - 2)
        slope_stderr = (residual_var / x_var) ** 0.5 if x_var else None
        if not slope_stderr:
            tstat = 0.0
        else:
            tstat = slope / slope_stderr
        candidate = {
            "trend_scan_tstat": tstat,
            "trend_scan_bars": bars,
            "trend_scan_return_pct": _pct_change(closes[idx], y_values[-1]),
        }
        if best is None or abs(tstat) > abs(float(best["trend_scan_tstat"])):
            best = candidate

    if best is None:
        return {
            "trend_scan_label": None,
            "trend_scan_tstat": None,
            "trend_scan_bars": None,
            "trend_scan_return_pct": None,
            "trend_scan_reason": "trend_scan_unavailable",
        }
    tstat = float(best["trend_scan_tstat"])
    label = 1 if tstat >= 2.0 else (-1 if tstat <= -2.0 else 0)
    return {
        **best,
        "trend_scan_label": label,
        "trend_scan_reason": (
            "positive_structural_trend"
            if label == 1
            else "negative_structural_trend"
            if label == -1
            else "no_stable_directional_trend"
        ),
    }


def _rolling_avg_at(values: list[float], idx: int, window: int) -> float | None:
    if idx + 1 < window:
        return None
    sample = values[idx + 1 - window : idx + 1]
    if not sample:
        return None
    return sum(sample) / len(sample)


def _candle_physics(
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    atr: float | None,
    avg_volume: float | None,
    volume: float,
    pressure_return_3: float | None,
) -> dict[str, float | None]:
    total_range = max(0.0, high - low)
    body = abs(close - open_price)
    upper_wick = max(0.0, high - max(open_price, close))
    lower_wick = max(0.0, min(open_price, close) - low)
    close_location = _safe_div(close - low, total_range)
    range_atr_ratio = _safe_div(total_range, atr)
    atr_pct = _pct_change(close, close + atr) if atr is not None else None
    volume_ratio = _safe_div(volume, avg_volume)
    return {
        "candle_body_pct": _safe_div(body, total_range),
        "upper_wick_pct": _safe_div(upper_wick, total_range),
        "lower_wick_pct": _safe_div(lower_wick, total_range),
        "upper_lower_wick_ratio": _safe_div(upper_wick, lower_wick),
        "close_location": close_location,
        "range_atr_ratio": range_atr_ratio,
        "atr_20_pct": atr_pct,
        "volume_ratio_20": volume_ratio,
        "volume_weighted_pressure_3": (
            pressure_return_3 * volume_ratio
            if pressure_return_3 is not None and volume_ratio is not None
            else None
        ),
    }


def _triple_barrier_label(
    *,
    close: float,
    future_highs: list[float],
    future_lows: list[float],
    atr_pct: float | None,
    profit_multiplier: float = 1.25,
    stop_multiplier: float = 0.85,
) -> dict[str, Any]:
    if not future_highs or not future_lows or atr_pct is None or atr_pct <= 0:
        return {
            "triple_barrier_label": None,
            "triple_barrier_reason": "insufficient_volatility_or_forward_bars",
            "triple_barrier_bars_to_event": None,
            "triple_barrier_profit_pct": None,
            "triple_barrier_stop_pct": None,
        }

    profit_pct = max(0.05, atr_pct * profit_multiplier)
    stop_pct = max(0.05, atr_pct * stop_multiplier)
    upper = close * (1.0 + profit_pct / 100.0)
    lower = close * (1.0 - stop_pct / 100.0)
    for offset, (high, low) in enumerate(zip(future_highs, future_lows), start=1):
        hit_upper = high >= upper
        hit_lower = low <= lower
        if hit_upper and hit_lower:
            return {
                "triple_barrier_label": -1,
                "triple_barrier_reason": "both_barriers_same_bar_stop_first_conservative",
                "triple_barrier_bars_to_event": offset,
                "triple_barrier_profit_pct": profit_pct,
                "triple_barrier_stop_pct": stop_pct,
            }
        if hit_upper:
            return {
                "triple_barrier_label": 1,
                "triple_barrier_reason": "profit_target_first",
                "triple_barrier_bars_to_event": offset,
                "triple_barrier_profit_pct": profit_pct,
                "triple_barrier_stop_pct": stop_pct,
            }
        if hit_lower:
            return {
                "triple_barrier_label": -1,
                "triple_barrier_reason": "stop_loss_first",
                "triple_barrier_bars_to_event": offset,
                "triple_barrier_profit_pct": profit_pct,
                "triple_barrier_stop_pct": stop_pct,
            }
    return {
        "triple_barrier_label": 0,
        "triple_barrier_reason": "vertical_timeout",
        "triple_barrier_bars_to_event": len(future_highs),
        "triple_barrier_profit_pct": profit_pct,
        "triple_barrier_stop_pct": stop_pct,
    }


def _label_pattern(
    *,
    close: float,
    sma20: float | None,
    prev_high_20: float | None,
    efi_ema: float | None,
    efi_slope_3: float | None,
    pvt_slope_5: float | None,
    price_return_5: float | None,
    pvt_new_high_30: bool,
) -> tuple[str, float]:
    score = 50.0
    if price_return_5 is not None and price_return_5 > 0:
        score += 8
    elif price_return_5 is not None and price_return_5 < 0:
        score -= 8
    if efi_ema is not None and efi_ema > 0:
        score += 10
    elif efi_ema is not None and efi_ema < 0:
        score -= 10
    if pvt_slope_5 is not None and pvt_slope_5 > 0:
        score += 10
    elif pvt_slope_5 is not None and pvt_slope_5 < 0:
        score -= 10
    if pvt_new_high_30:
        score += 8
    if efi_slope_3 is not None and efi_slope_3 < 0 and (price_return_5 or 0) > 0:
        score -= 8

    breakout = bool(prev_high_20 is not None and close >= prev_high_20)
    above_sma = bool(sma20 is not None and close >= sma20)
    force_positive = bool(efi_ema is not None and efi_ema > 0)
    pvt_positive = bool(pvt_slope_5 is not None and pvt_slope_5 > 0)

    if breakout and force_positive and pvt_positive:
        return "volume_confirmed_breakout", min(100.0, score + 8)
    if above_sma and force_positive and pvt_positive:
        return "constructive_continuation", min(100.0, score)
    if above_sma and (price_return_5 or 0) > 0 and (not pvt_positive or (efi_slope_3 or 0) < 0):
        return "bearish_divergence", max(0.0, score - 10)
    if not above_sma and not force_positive and not pvt_positive:
        return "bearish_distribution", max(0.0, score)
    if abs(price_return_5 or 0.0) < 0.20 and pvt_positive and force_positive:
        return "accumulation_base", min(100.0, score)
    return "mixed_bar_pattern", max(0.0, min(100.0, score))


def _label_hindsight_opportunity(
    *,
    forward_return: float | None,
    forward_mfe: float | None,
    forward_mae: float | None,
) -> tuple[str, str, float | None, float | None]:
    if forward_return is None or forward_mfe is None or forward_mae is None:
        return "unknown", "insufficient_forward_bars", None, None

    adverse = abs(min(0.0, forward_mae))
    upside = max(0.0, forward_mfe)
    downside = abs(min(0.0, forward_mae))
    favorable_return = max(0.0, forward_return)
    negative_return = abs(min(0.0, forward_return))

    long_score = _clamp(50.0 + upside * 28.0 + favorable_return * 18.0 - adverse * 22.0)
    sell_score = _clamp(50.0 + downside * 28.0 + negative_return * 18.0 - upside * 20.0)

    if forward_mfe >= 0.75 and forward_return >= 0.25 and forward_mae > -0.45:
        return "buy_candidate", "best_buy_window", long_score, sell_score
    if forward_mfe >= 0.40 and forward_return >= 0.05 and forward_mae > -0.65:
        return "buy_candidate", "good_buy_window", long_score, sell_score
    if forward_mae <= -0.75 and forward_return <= -0.25:
        return "sell_or_avoid_candidate", "best_sell_or_avoid_window", long_score, sell_score
    if forward_mae <= -0.40 and forward_return <= -0.05:
        return "sell_or_avoid_candidate", "good_sell_or_avoid_window", long_score, sell_score
    return "hold_or_wait", "mixed_forward_window", long_score, sell_score


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _summarize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_label: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get("pattern_label") or "unknown")
        by_label.setdefault(label, []).append(row)

    summary = []
    for label, label_rows in by_label.items():
        summary.append(
            {
                "pattern_label": label,
                "rows": len(label_rows),
                "avg_forward_return_pct": _avg(
                    [
                        float(row["forward_return_pct"])
                        for row in label_rows
                        if row.get("forward_return_pct") is not None
                    ]
                ),
                "avg_forward_mfe_pct": _avg(
                    [
                        float(row["forward_mfe_pct"])
                        for row in label_rows
                        if row.get("forward_mfe_pct") is not None
                    ]
                ),
                "avg_forward_mae_pct": _avg(
                    [
                        float(row["forward_mae_pct"])
                        for row in label_rows
                        if row.get("forward_mae_pct") is not None
                    ]
                ),
            }
        )
    return sorted(summary, key=lambda row: (-int(row["rows"]), str(row["pattern_label"])))


def _summarize_opportunities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_label: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("opportunity_action") or "unknown"),
            str(row.get("opportunity_quality") or "unknown"),
        )
        by_label.setdefault(key, []).append(row)

    summary = []
    for (action, quality), label_rows in by_label.items():
        summary.append(
            {
                "opportunity_action": action,
                "opportunity_quality": quality,
                "rows": len(label_rows),
                "avg_long_opportunity_score": _avg(
                    [
                        float(row["long_opportunity_score"])
                        for row in label_rows
                        if row.get("long_opportunity_score") is not None
                    ]
                ),
                "avg_sell_opportunity_score": _avg(
                    [
                        float(row["sell_opportunity_score"])
                        for row in label_rows
                        if row.get("sell_opportunity_score") is not None
                    ]
                ),
                "avg_forward_return_pct": _avg(
                    [
                        float(row["forward_return_pct"])
                        for row in label_rows
                        if row.get("forward_return_pct") is not None
                    ]
                ),
                "avg_forward_mfe_pct": _avg(
                    [
                        float(row["forward_mfe_pct"])
                        for row in label_rows
                        if row.get("forward_mfe_pct") is not None
                    ]
                ),
                "avg_forward_mae_pct": _avg(
                    [
                        float(row["forward_mae_pct"])
                        for row in label_rows
                        if row.get("forward_mae_pct") is not None
                    ]
                ),
            }
        )
    return sorted(
        summary,
        key=lambda row: (
            -int(row["rows"]),
            str(row["opportunity_action"]),
            str(row["opportunity_quality"]),
        ),
    )


@dataclass(frozen=True)
class BarPatternBackfillResult:
    report_version: str
    runtime_effect: str
    symbol: str
    date: str
    timeframe: str
    bars: int
    feature_rows: int
    persisted_rows: int
    rows_with_forward_outcome: int
    rows_with_raw_bar_contract: int
    rows_with_source: int
    rows_with_adjustment_flag: int
    rows_with_trade_count: int
    rows_with_bollinger_context: int
    rows_with_temporal_context: int
    rows_with_microstructure_context: int
    label_summary: list[dict[str, Any]]
    opportunity_summary: list[dict[str, Any]]
    error: str | None = None


class BarPatternFeatureService:
    def __init__(self, repository: BarPatternFeatureRepository | None = None):
        self.repository = repository or BarPatternFeatureRepository()

    def build_features(
        self,
        bars: list[Any],
        *,
        symbol: str,
        timeframe: str = "5m",
        horizon_bars: int = 12,
        bar_source: str = "unknown_bar_source",
        bar_feed: str | None = None,
        adjusted: bool | None = None,
        interval_semantics: str = "inclusive_start_1m",
    ) -> list[dict[str, Any]]:
        normalized = [
            bar
            for bar in (normalize_bar(item) for item in bars)
            if bar["timestamp"] and bar["close"] is not None
        ]
        normalized.sort(key=lambda item: item["timestamp"])
        if len(normalized) < 21:
            return []

        closes = [float(bar["close"]) for bar in normalized]
        opens = [
            float(bar["open"] if bar["open"] is not None else bar["close"]) for bar in normalized
        ]
        highs = [
            float(bar["high"] if bar["high"] is not None else bar["close"]) for bar in normalized
        ]
        lows = [float(bar["low"] if bar["low"] is not None else bar["close"]) for bar in normalized]
        volumes = [float(bar["volume"] or 0.0) for bar in normalized]
        vwaps = [
            float(bar["vwap"] if bar.get("vwap") is not None else bar["close"])
            for bar in normalized
        ]
        true_ranges = _true_ranges(highs, lows, closes)

        efi_raw = [0.0]
        pvt = [0.0]
        trade_directions = [0.0]
        volume_delta = [0.0]
        institutional_volume_delta = [0.0]
        cumulative_volume_delta = [0.0]
        last_direction = 0.0
        current_session_date = str(normalized[0]["timestamp"])[:10]
        session_cvd = 0.0
        for idx in range(1, len(normalized)):
            change = closes[idx] - closes[idx - 1]
            direction = 1.0 if change > 0 else (-1.0 if change < 0 else last_direction)
            last_direction = direction if direction else last_direction
            efi_raw.append(change * volumes[idx])
            pct = change / closes[idx - 1] if closes[idx - 1] else 0.0
            pvt.append(pvt[-1] + volumes[idx] * pct)
            trade_directions.append(direction)
            volume_delta.append(direction * volumes[idx])
            session_date = str(normalized[idx]["timestamp"])[:10]
            if session_date != current_session_date:
                current_session_date = session_date
                session_cvd = 0.0
            volume_cutoff = _quantile(volumes[max(0, idx - 59) : idx + 1], 0.65) or 0.0
            inst_delta = direction * volumes[idx] if volumes[idx] >= volume_cutoff else 0.0
            institutional_volume_delta.append(inst_delta)
            session_cvd += inst_delta
            cumulative_volume_delta.append(session_cvd)
        fractional_diff_close = [
            _fractional_diff_at(closes, idx, d=0.45) for idx in range(len(normalized))
        ]
        webull_rsi_14_values = _wilder_rsi(closes, 14)
        market_dts = [_parse_timestamp(row["timestamp"]) for row in normalized]
        market_dates = [dt.date() if dt else None for dt in market_dts]
        prior_session_closes: list[float | None] = []
        prior_5_session_closes: list[float | None] = []
        seen_dates = []
        last_close_by_date: dict[Any, float] = {}
        for idx, market_date in enumerate(market_dates):
            prior_dates = [item for item in seen_dates if item != market_date]
            prior_session = prior_dates[-1] if prior_dates else None
            prior_5_session = prior_dates[-5] if len(prior_dates) >= 5 else None
            prior_session_closes.append(
                last_close_by_date.get(prior_session) if prior_session is not None else None
            )
            prior_5_session_closes.append(
                last_close_by_date.get(prior_5_session) if prior_5_session is not None else None
            )
            if market_date is not None:
                last_close_by_date[market_date] = closes[idx]
                if not seen_dates or seen_dates[-1] != market_date:
                    seen_dates.append(market_date)
        efi_ema = _ema(efi_raw, 13)
        ema_12 = _ema(closes, 12)
        ema_26 = _ema(closes, 26)
        macd_values = [fast - slow for fast, slow in zip(ema_12[-len(ema_26) :], ema_26)]
        macd_offset = len(closes) - len(macd_values)
        macd_signal_values = _ema(macd_values, 9)
        macd_signal_offset = len(closes) - len(macd_signal_values)

        rows = []
        for idx in range(20, len(normalized)):
            close = closes[idx]
            vwap = vwaps[idx]
            closes_20 = closes[idx - 19 : idx + 1]
            returns_20 = [
                (closes[pos] - closes[pos - 1]) / closes[pos - 1] * 100.0
                for pos in range(max(1, idx - 19), idx + 1)
                if closes[pos - 1]
            ]
            sma20 = sum(closes_20) / 20.0
            bollinger_std_20 = _std(closes_20)
            bollinger_upper_20 = (
                sma20 + 2.0 * bollinger_std_20 if bollinger_std_20 is not None else None
            )
            bollinger_lower_20 = (
                sma20 - 2.0 * bollinger_std_20 if bollinger_std_20 is not None else None
            )
            bollinger_width_20_pct = (
                (bollinger_upper_20 - bollinger_lower_20) / sma20 * 100.0
                if bollinger_upper_20 is not None and bollinger_lower_20 is not None and sma20
                else None
            )
            bollinger_percent_b_20 = (
                (close - bollinger_lower_20) / (bollinger_upper_20 - bollinger_lower_20)
                if bollinger_upper_20 is not None
                and bollinger_lower_20 is not None
                and (bollinger_upper_20 - bollinger_lower_20)
                else None
            )
            rolling_volatility_20_pct = _std(returns_20)
            market_dt = _parse_timestamp(normalized[idx]["timestamp"])
            day_of_week = market_dt.weekday() if market_dt else None
            minute_of_day = market_dt.hour * 60 + market_dt.minute if market_dt else None
            day_of_month = market_dt.day if market_dt else None
            week_of_month = ((market_dt.day - 1) // 7 + 1) if market_dt else None
            month_end_proximity_days = _month_end_proximity_days(market_dt)
            monday_volatility_flag = 1 if day_of_week == 0 else 0
            friday_rebalance_flag = (
                1
                if day_of_week == 4
                and month_end_proximity_days is not None
                and month_end_proximity_days <= 7
                else 0
            )
            session_phase = _session_phase(market_dt)
            prior_session_return_pct = _pct_change(prior_session_closes[idx], close)
            prior_5_session_return_pct = _pct_change(prior_5_session_closes[idx], close)
            prev_high_20 = max(highs[idx - 20 : idx]) if idx >= 20 else None
            price_return_5 = _pct_change(closes[idx - 5], close) if idx >= 5 else None
            pressure_return_3 = _pct_change(closes[idx - 3], close) if idx >= 3 else None
            pressure_return_8 = _pct_change(closes[idx - 8], close) if idx >= 8 else None
            price_vs_sma = _pct_change(sma20, close)
            atr20 = _rolling_avg_at(true_ranges, idx, 20)
            avg_volume_20 = _rolling_avg_at(volumes, idx, 20)
            candle = _candle_physics(
                open_price=opens[idx],
                high=highs[idx],
                low=lows[idx],
                close=close,
                atr=atr20,
                avg_volume=avg_volume_20,
                volume=volumes[idx],
                pressure_return_3=pressure_return_3,
            )
            efi_slope_3 = (
                efi_ema[idx] - efi_ema[idx - 3] if idx >= 3 and len(efi_ema) > idx else None
            )
            pvt_slope_5 = pvt[idx] - pvt[idx - 5] if idx >= 5 else None
            pvt_new_high_30 = idx >= 30 and pvt[idx] >= max(pvt[idx - 30 : idx + 1])
            pattern_label, pattern_score = _label_pattern(
                close=close,
                sma20=sma20,
                prev_high_20=prev_high_20,
                efi_ema=efi_ema[idx],
                efi_slope_3=efi_slope_3,
                pvt_slope_5=pvt_slope_5,
                price_return_5=price_return_5,
                pvt_new_high_30=pvt_new_high_30,
            )

            future_closes = closes[idx + 1 : idx + 1 + horizon_bars]
            future_highs = highs[idx + 1 : idx + 1 + horizon_bars]
            future_lows = lows[idx + 1 : idx + 1 + horizon_bars]
            forward_return = _pct_change(close, future_closes[-1]) if future_closes else None
            forward_mfe = _pct_change(close, max(future_highs)) if future_highs else None
            forward_mae = _pct_change(close, min(future_lows)) if future_lows else None
            triple_barrier = _triple_barrier_label(
                close=close,
                future_highs=future_highs,
                future_lows=future_lows,
                atr_pct=candle["atr_20_pct"],
            )
            trend_scan = _trend_scan_label(
                closes=closes,
                idx=idx,
                max_bars=horizon_bars,
            )
            corr_start = max(0, idx - 19)
            cvd_price_corr_20 = _rolling_corr(
                closes[corr_start : idx + 1],
                cumulative_volume_delta[corr_start : idx + 1],
            )
            volume_sum_20 = sum(volumes[corr_start : idx + 1])
            signed_volume_sum_20 = sum(abs(value) for value in volume_delta[corr_start : idx + 1])
            vpin_toxicity_20 = _safe_div(signed_volume_sum_20, volume_sum_20)
            cvd_change_5 = (
                cumulative_volume_delta[idx] - cumulative_volume_delta[idx - 5]
                if idx >= 5
                else None
            )
            cvd_divergence_label = "none"
            if price_return_5 is not None and cvd_change_5 is not None:
                if price_return_5 < 0 and cvd_change_5 > 0:
                    cvd_divergence_label = "bullish_absorption"
                elif price_return_5 > 0 and cvd_change_5 < 0:
                    cvd_divergence_label = "bearish_distribution"
            frac_window = [
                value
                for value in fractional_diff_close[max(0, idx - 19) : idx + 1]
                if value is not None
            ]
            fractional_diff_zscore_20 = _zscore(frac_window)
            opportunity_action, opportunity_quality, long_score, sell_score = (
                _label_hindsight_opportunity(
                    forward_return=forward_return,
                    forward_mfe=forward_mfe,
                    forward_mae=forward_mae,
                )
            )
            macd_idx = idx - macd_offset
            macd = macd_values[macd_idx] if 0 <= macd_idx < len(macd_values) else None
            macd_signal_idx = idx - macd_signal_offset
            macd_signal = (
                macd_signal_values[macd_signal_idx]
                if 0 <= macd_signal_idx < len(macd_signal_values)
                else None
            )
            interval_start_ts = (
                normalized[idx].get("interval_start") or normalized[idx]["timestamp"]
            )
            row_source = str(normalized[idx].get("source") or bar_source or "unknown_bar_source")
            row_feed = normalized[idx].get("feed") or bar_feed
            row_adjusted_raw = normalized[idx].get("adjusted")
            if row_adjusted_raw is None:
                row_adjusted = None if adjusted is None else int(bool(adjusted))
            elif isinstance(row_adjusted_raw, str):
                row_adjusted = 1 if row_adjusted_raw.strip().lower() in {"1", "true", "yes"} else 0
            else:
                row_adjusted = int(bool(row_adjusted_raw))
            row_interval_semantics = (
                normalized[idx].get("interval_semantics")
                or interval_semantics
                or "inclusive_start_1m"
            )
            bid_price = normalized[idx].get("bid_price")
            ask_price = normalized[idx].get("ask_price")
            bid_ask_spread_pct = normalized[idx].get("bid_ask_spread_pct")
            slippage_estimate_pct = normalized[idx].get("slippage_estimate_pct")
            execution_cost_estimate_pct = normalized[idx].get("execution_cost_estimate_pct")
            liquidity_zone_label = normalized[idx].get("liquidity_zone_label")
            liquidity_sweep_risk = normalized[idx].get("liquidity_sweep_risk")
            webull_rsi_14 = webull_rsi_14_values[idx]
            previous_webull_rsi_14 = webull_rsi_14_values[idx - 1] if idx > 0 else None
            webull_rsi_zone = _webull_rsi_zone(webull_rsi_14)
            webull_rsi_exit_signal = _webull_rsi_exit_signal(
                previous_webull_rsi_14,
                webull_rsi_14,
            )
            webull_rsi_bearish_divergence = _webull_rsi_bearish_divergence(
                closes,
                webull_rsi_14_values,
                idx,
            )

            feature_json = {
                "bar_source": row_source,
                "bar_feed": row_feed,
                "bar_adjusted": row_adjusted,
                "bar_trade_count": normalized[idx].get("trade_count"),
                "bar_interval_start_ts": interval_start_ts,
                "bar_interval_semantics": row_interval_semantics,
                "open": opens[idx],
                "high": highs[idx],
                "low": lows[idx],
                "close": close,
                "volume": volumes[idx],
                "vwap": vwap,
                "sma_20": sma20,
                "prev_high_20": prev_high_20,
                "bollinger_upper_20": bollinger_upper_20,
                "bollinger_lower_20": bollinger_lower_20,
                "bollinger_width_20_pct": bollinger_width_20_pct,
                "bollinger_percent_b_20": bollinger_percent_b_20,
                "rolling_volatility_20_pct": rolling_volatility_20_pct,
                "day_of_week": day_of_week,
                "minute_of_day": minute_of_day,
                "day_of_month": day_of_month,
                "week_of_month": week_of_month,
                "month_end_proximity_days": month_end_proximity_days,
                "monday_volatility_flag": monday_volatility_flag,
                "friday_rebalance_flag": friday_rebalance_flag,
                "prior_session_return_pct": prior_session_return_pct,
                "prior_5_session_return_pct": prior_5_session_return_pct,
                "session_phase": session_phase,
                "bid_price": bid_price,
                "ask_price": ask_price,
                "bid_ask_spread_pct": bid_ask_spread_pct,
                "slippage_estimate_pct": slippage_estimate_pct,
                "execution_cost_estimate_pct": execution_cost_estimate_pct,
                "liquidity_zone_label": liquidity_zone_label,
                "liquidity_sweep_risk": liquidity_sweep_risk,
                "ema_12": ema_12[idx],
                "ema_26": ema_26[idx],
                "macd": macd,
                "macd_signal": macd_signal,
                "rsi_14": _rsi_at(closes, idx, 14),
                "webull_rsi_14": webull_rsi_14,
                "webull_rsi_zone": webull_rsi_zone,
                "webull_rsi_exit_signal": webull_rsi_exit_signal,
                "webull_rsi_bearish_divergence": webull_rsi_bearish_divergence,
                "efi": efi_raw[idx],
                "efi_ema_13": efi_ema[idx],
                "efi_slope_3": efi_slope_3,
                "pvt": pvt[idx],
                "pvt_slope_5": pvt_slope_5,
                "pvt_new_high_30": pvt_new_high_30,
                "candle_body_pct": candle["candle_body_pct"],
                "upper_wick_pct": candle["upper_wick_pct"],
                "lower_wick_pct": candle["lower_wick_pct"],
                "upper_lower_wick_ratio": candle["upper_lower_wick_ratio"],
                "close_location": candle["close_location"],
                "range_atr_ratio": candle["range_atr_ratio"],
                "atr_20_pct": candle["atr_20_pct"],
                "volume_ratio_20": candle["volume_ratio_20"],
                "pressure_return_3": pressure_return_3,
                "pressure_return_8": pressure_return_8,
                "volume_weighted_pressure_3": candle["volume_weighted_pressure_3"],
                "trade_direction": trade_directions[idx],
                "volume_delta": volume_delta[idx],
                "institutional_volume_delta": institutional_volume_delta[idx],
                "cumulative_volume_delta": cumulative_volume_delta[idx],
                "cvd_price_corr_20": cvd_price_corr_20,
                "cvd_divergence_label": cvd_divergence_label,
                "vpin_toxicity_20": vpin_toxicity_20,
                "fractional_diff_close_045": fractional_diff_close[idx],
                "fractional_diff_zscore_20": fractional_diff_zscore_20,
                **trend_scan,
                **triple_barrier,
                "price_return_5": price_return_5,
                "price_vs_sma_20_pct": price_vs_sma,
                "opportunity_action": opportunity_action,
                "opportunity_quality": opportunity_quality,
                "long_opportunity_score": long_score,
                "sell_opportunity_score": sell_score,
            }
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "bar_timestamp": normalized[idx]["timestamp"],
                    "bar_source": row_source,
                    "bar_feed": row_feed,
                    "bar_adjusted": row_adjusted,
                    "bar_trade_count": _round(normalized[idx].get("trade_count")),
                    "bar_interval_start_ts": interval_start_ts,
                    "bar_interval_semantics": row_interval_semantics,
                    "timeframe": timeframe,
                    "open": _round(opens[idx]),
                    "high": _round(highs[idx]),
                    "low": _round(lows[idx]),
                    "close": _round(close),
                    "volume": _round(volumes[idx]),
                    "vwap": _round(vwap),
                    "sma_20": _round(sma20),
                    "bollinger_upper_20": _round(bollinger_upper_20),
                    "bollinger_lower_20": _round(bollinger_lower_20),
                    "bollinger_width_20_pct": _round(bollinger_width_20_pct),
                    "bollinger_percent_b_20": _round(bollinger_percent_b_20),
                    "rolling_volatility_20_pct": _round(rolling_volatility_20_pct),
                    "day_of_week": day_of_week,
                    "minute_of_day": minute_of_day,
                    "day_of_month": day_of_month,
                    "week_of_month": week_of_month,
                    "month_end_proximity_days": month_end_proximity_days,
                    "monday_volatility_flag": monday_volatility_flag,
                    "friday_rebalance_flag": friday_rebalance_flag,
                    "prior_session_return_pct": _round(prior_session_return_pct),
                    "prior_5_session_return_pct": _round(prior_5_session_return_pct),
                    "session_phase": session_phase,
                    "bid_price": _round(bid_price),
                    "ask_price": _round(ask_price),
                    "bid_ask_spread_pct": _round(bid_ask_spread_pct),
                    "slippage_estimate_pct": _round(slippage_estimate_pct),
                    "execution_cost_estimate_pct": _round(execution_cost_estimate_pct),
                    "liquidity_zone_label": liquidity_zone_label,
                    "liquidity_sweep_risk": _round(liquidity_sweep_risk),
                    "ema_12": _round(ema_12[idx]),
                    "ema_26": _round(ema_26[idx]),
                    "macd": _round(macd),
                    "macd_signal": _round(macd_signal),
                    "rsi_14": _round(_rsi_at(closes, idx, 14)),
                    "webull_rsi_14": _round(webull_rsi_14),
                    "webull_rsi_zone": webull_rsi_zone,
                    "webull_rsi_exit_signal": webull_rsi_exit_signal,
                    "webull_rsi_bearish_divergence": webull_rsi_bearish_divergence,
                    "efi": _round(efi_raw[idx]),
                    "efi_ema_13": _round(efi_ema[idx]),
                    "efi_slope_3": _round(efi_slope_3),
                    "efi_zscore_20": _round(_zscore(efi_raw[idx - 19 : idx + 1])),
                    "pvt": _round(pvt[idx]),
                    "pvt_slope_5": _round(pvt_slope_5),
                    "pvt_new_high_30": 1 if pvt_new_high_30 else 0,
                    "price_return_5": _round(price_return_5),
                    "price_vs_sma_20_pct": _round(price_vs_sma),
                    "breakout_20": 1 if prev_high_20 is not None and close >= prev_high_20 else 0,
                    "candle_body_pct": _round(candle["candle_body_pct"]),
                    "upper_wick_pct": _round(candle["upper_wick_pct"]),
                    "lower_wick_pct": _round(candle["lower_wick_pct"]),
                    "upper_lower_wick_ratio": _round(candle["upper_lower_wick_ratio"]),
                    "close_location": _round(candle["close_location"]),
                    "range_atr_ratio": _round(candle["range_atr_ratio"]),
                    "atr_20_pct": _round(candle["atr_20_pct"]),
                    "volume_ratio_20": _round(candle["volume_ratio_20"]),
                    "pressure_return_3": _round(pressure_return_3),
                    "pressure_return_8": _round(pressure_return_8),
                    "volume_weighted_pressure_3": _round(candle["volume_weighted_pressure_3"]),
                    "trade_direction": _round(trade_directions[idx]),
                    "volume_delta": _round(volume_delta[idx]),
                    "institutional_volume_delta": _round(institutional_volume_delta[idx]),
                    "cumulative_volume_delta": _round(cumulative_volume_delta[idx]),
                    "cvd_price_corr_20": _round(cvd_price_corr_20),
                    "cvd_divergence_label": cvd_divergence_label,
                    "vpin_toxicity_20": _round(vpin_toxicity_20),
                    "fractional_diff_close_045": _round(fractional_diff_close[idx]),
                    "fractional_diff_zscore_20": _round(fractional_diff_zscore_20),
                    "trend_scan_label": trend_scan["trend_scan_label"],
                    "trend_scan_tstat": _round(trend_scan["trend_scan_tstat"]),
                    "trend_scan_bars": trend_scan["trend_scan_bars"],
                    "trend_scan_return_pct": _round(trend_scan["trend_scan_return_pct"]),
                    "trend_scan_reason": trend_scan["trend_scan_reason"],
                    "triple_barrier_label": triple_barrier["triple_barrier_label"],
                    "triple_barrier_reason": triple_barrier["triple_barrier_reason"],
                    "triple_barrier_bars_to_event": triple_barrier["triple_barrier_bars_to_event"],
                    "triple_barrier_profit_pct": _round(
                        triple_barrier["triple_barrier_profit_pct"]
                    ),
                    "triple_barrier_stop_pct": _round(triple_barrier["triple_barrier_stop_pct"]),
                    "pattern_label": pattern_label,
                    "pattern_score": _round(pattern_score, 4),
                    "opportunity_action": opportunity_action,
                    "opportunity_quality": opportunity_quality,
                    "long_opportunity_score": _round(long_score, 4),
                    "sell_opportunity_score": _round(sell_score, 4),
                    "forward_return_pct": _round(forward_return),
                    "forward_mfe_pct": _round(forward_mfe),
                    "forward_mae_pct": _round(forward_mae),
                    "horizon_bars": horizon_bars,
                    "feature_version": BAR_PATTERN_FEATURE_VERSION,
                    "runtime_effect": BAR_PATTERN_RUNTIME_EFFECT,
                    "feature_json": feature_json,
                }
            )
        return rows

    def persist_features(
        self,
        bars: list[Any],
        *,
        symbol: str,
        target_date: str,
        timeframe: str = "5m",
        horizon_bars: int = 12,
        bar_source: str = "unknown_bar_source",
        bar_feed: str | None = None,
        adjusted: bool | None = None,
        interval_semantics: str = "inclusive_start_1m",
        dry_run: bool = False,
    ) -> BarPatternBackfillResult:
        rows = self.build_features(
            bars,
            symbol=symbol,
            timeframe=timeframe,
            horizon_bars=horizon_bars,
            bar_source=bar_source,
            bar_feed=bar_feed,
            adjusted=adjusted,
            interval_semantics=interval_semantics,
        )
        label_summary = _summarize_rows(rows)
        opportunity_summary = _summarize_opportunities(rows)
        persisted = 0 if dry_run else self.repository.upsert_many(rows)
        return BarPatternBackfillResult(
            report_version="bar_pattern_feature_backfill_v1",
            runtime_effect=BAR_PATTERN_RUNTIME_EFFECT,
            symbol=symbol.upper(),
            date=target_date,
            timeframe=timeframe,
            bars=len(bars),
            feature_rows=len(rows),
            persisted_rows=persisted,
            rows_with_forward_outcome=sum(
                1 for row in rows if row.get("forward_return_pct") is not None
            ),
            rows_with_raw_bar_contract=sum(
                1
                for row in rows
                if row.get("open") is not None
                and row.get("high") is not None
                and row.get("low") is not None
                and row.get("close") is not None
                and row.get("volume") is not None
                and row.get("vwap") is not None
                and row.get("bar_interval_start_ts") is not None
            ),
            rows_with_source=sum(1 for row in rows if row.get("bar_source")),
            rows_with_adjustment_flag=sum(1 for row in rows if row.get("bar_adjusted") is not None),
            rows_with_trade_count=sum(1 for row in rows if row.get("bar_trade_count") is not None),
            rows_with_bollinger_context=sum(
                1 for row in rows if row.get("bollinger_percent_b_20") is not None
            ),
            rows_with_temporal_context=sum(
                1 for row in rows if row.get("minute_of_day") is not None
            ),
            rows_with_microstructure_context=sum(
                1
                for row in rows
                if row.get("bid_ask_spread_pct") is not None
                or row.get("slippage_estimate_pct") is not None
                or row.get("execution_cost_estimate_pct") is not None
                or row.get("liquidity_sweep_risk") is not None
            ),
            label_summary=label_summary,
            opportunity_summary=opportunity_summary,
        )

    def summary(self, target_date: str, symbol: str | None = None) -> dict[str, Any]:
        return self.repository.summary(target_date, symbol=symbol)
