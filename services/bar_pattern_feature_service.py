"""EFI/PVT bar-pattern feature extraction for observe-only learning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository


BAR_PATTERN_FEATURE_VERSION = "efi_pvt_candle_physics_bar_pattern_v2"
BAR_PATTERN_RUNTIME_EFFECT = "observe_only_pattern_learning_no_live_authority"


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


def normalize_bar(bar: Any) -> dict[str, Any]:
    return {
        "timestamp": _timestamp(_bar_value(bar, "timestamp", "t")),
        "open": _float(_bar_value(bar, "open", "o")),
        "high": _float(_bar_value(bar, "high", "h")),
        "low": _float(_bar_value(bar, "low", "l")),
        "close": _float(_bar_value(bar, "close", "c")),
        "volume": _float(_bar_value(bar, "volume", "v")),
    }


def _ema(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (window + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * alpha + out[-1] * (1.0 - alpha))
    return out


def _zscore(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = variance ** 0.5
    if not std:
        return 0.0
    return (values[-1] - mean) / std


def _pct_change(old: float | None, new: float | None) -> float | None:
    if old in (None, 0) or new is None:
        return None
    return (new - old) / old * 100.0


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


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
        key=lambda row: (-int(row["rows"]), str(row["opportunity_action"]), str(row["opportunity_quality"])),
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
    ) -> list[dict[str, Any]]:
        normalized = [
            bar for bar in (normalize_bar(item) for item in bars)
            if bar["timestamp"] and bar["close"] is not None
        ]
        normalized.sort(key=lambda item: item["timestamp"])
        if len(normalized) < 21:
            return []

        closes = [float(bar["close"]) for bar in normalized]
        opens = [float(bar["open"] if bar["open"] is not None else bar["close"]) for bar in normalized]
        highs = [float(bar["high"] if bar["high"] is not None else bar["close"]) for bar in normalized]
        lows = [float(bar["low"] if bar["low"] is not None else bar["close"]) for bar in normalized]
        volumes = [float(bar["volume"] or 0.0) for bar in normalized]
        true_ranges = _true_ranges(highs, lows, closes)

        efi_raw = [0.0]
        pvt = [0.0]
        for idx in range(1, len(normalized)):
            change = closes[idx] - closes[idx - 1]
            efi_raw.append(change * volumes[idx])
            pct = change / closes[idx - 1] if closes[idx - 1] else 0.0
            pvt.append(pvt[-1] + volumes[idx] * pct)
        efi_ema = _ema(efi_raw, 13)

        rows = []
        for idx in range(20, len(normalized)):
            close = closes[idx]
            sma20 = sum(closes[idx - 19 : idx + 1]) / 20.0
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
                efi_ema[idx] - efi_ema[idx - 3]
                if idx >= 3 and len(efi_ema) > idx
                else None
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
            opportunity_action, opportunity_quality, long_score, sell_score = _label_hindsight_opportunity(
                forward_return=forward_return,
                forward_mfe=forward_mfe,
                forward_mae=forward_mae,
            )

            feature_json = {
                "close": close,
                "sma20": sma20,
                "prev_high_20": prev_high_20,
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
                    "timeframe": timeframe,
                    "close": _round(close),
                    "volume": _round(volumes[idx]),
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
                    "triple_barrier_label": triple_barrier["triple_barrier_label"],
                    "triple_barrier_reason": triple_barrier["triple_barrier_reason"],
                    "triple_barrier_bars_to_event": triple_barrier["triple_barrier_bars_to_event"],
                    "triple_barrier_profit_pct": _round(triple_barrier["triple_barrier_profit_pct"]),
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
        dry_run: bool = False,
    ) -> BarPatternBackfillResult:
        rows = self.build_features(
            bars,
            symbol=symbol,
            timeframe=timeframe,
            horizon_bars=horizon_bars,
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
            label_summary=label_summary,
            opportunity_summary=opportunity_summary,
        )

    def summary(self, target_date: str, symbol: str | None = None) -> dict[str, Any]:
        return self.repository.summary(target_date, symbol=symbol)
