"""Diagnostic learning inputs for trend/pattern intelligence.

This service intentionally produces telemetry only.  It helps determine which
buy/sell pattern observations can feed offline learning without creating a
live authority path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from config.conviction import load_conviction_config

PATTERN_LEARNING_INPUTS_VERSION = "pattern_learning_inputs_v1"
PATTERN_LEARNING_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"

SYSTEM_PROBABILITY_SOURCES = {
    "probability_of_approval",
    "probability_of_order",
    "daily_symbol_predictions:probability_of_approval",
    "daily_symbol_predictions:probability_of_order",
}


@dataclass(frozen=True)
class PatternLearningInputsPayload:
    summary: dict[str, Any]
    executed_trade_quality: list[dict[str, Any]]
    expectancy_by_dimension: dict[str, list[dict[str, Any]]]
    candidate_label_coverage: dict[str, Any]
    bar_pattern_evidence: dict[str, Any]
    learning_actions: list[str]


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _bucket(row: dict[str, Any], key: str, default: str = "unknown") -> str:
    value = row.get(key)
    if value in (None, ""):
        return default
    return str(value)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _load_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _candidate_return(payload: dict[str, Any]) -> float | None:
    return _float(
        payload.get("forward_return_pct")
        or payload.get("return_60m")
        or payload.get("return_30m")
        or payload.get("return_eod")
    )


def _candidate_mfe(payload: dict[str, Any]) -> float | None:
    return _float(
        payload.get("forward_mfe_pct")
        or payload.get("max_favorable_60m")
        or payload.get("max_favorable_30m")
        or payload.get("max_favorable_eod")
    )


def _candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate")
    return candidate if isinstance(candidate, dict) else {}


def _candidate_value(
    row: dict[str, Any],
    payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    key: str,
) -> Any:
    for source in (candidate_payload, payload, row):
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _score_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    if value >= 23.0:
        return "23_plus"
    if value >= 20.0:
        return "20_to_22_99"
    if value >= 15.0:
        return "15_to_19_99"
    if value >= 10.0:
        return "10_to_14_99"
    if value >= 0.0:
        return "0_to_9_99"
    return "negative"


def _probability_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    if value >= 80.0:
        return "80_plus"
    if value >= 62.0:
        return "62_to_79_99"
    if value >= 50.0:
        return "50_to_61_99"
    return "below_50"


def _trade_quality(row: dict[str, Any]) -> str:
    pnl = _float(row.get("realized_pnl_pct"))
    mfe = _float(row.get("mfe_pct"))
    capture = _float(row.get("capture_ratio"))
    if pnl is None:
        return "missing_outcome"
    if pnl > 0 and capture is not None and capture >= 0.50:
        return "good_buy_good_sell"
    if pnl > 0:
        return "good_buy_partial_or_weak_sell"
    if mfe is not None and mfe >= 0.40:
        return "good_buy_poor_sell_or_late_exit"
    if mfe is not None and mfe < 0.20:
        return "bad_buy_or_no_edge"
    return "inconclusive_pattern_outcome"


def _expectancy(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    mfe_grouped: dict[str, list[float]] = {}
    capture_grouped: dict[str, list[float]] = {}
    for row in rows:
        outcome = _float(row.get("realized_pnl_pct"))
        if outcome is None:
            continue
        bucket = _bucket(row, key)
        grouped.setdefault(bucket, []).append(outcome)
        mfe = _float(row.get("mfe_pct"))
        if mfe is not None:
            mfe_grouped.setdefault(bucket, []).append(mfe)
        capture = _float(row.get("capture_ratio"))
        if capture is not None:
            capture_grouped.setdefault(bucket, []).append(capture)

    result = []
    for bucket, values in grouped.items():
        result.append(
            {
                "bucket": bucket,
                "rows": len(values),
                "win_rate": _rate(sum(1 for value in values if value > 0), len(values)),
                "avg_return_pct": _mean(values),
                "avg_mfe_pct": _mean(mfe_grouped.get(bucket, [])),
                "avg_capture_ratio": _mean(capture_grouped.get(bucket, [])),
            }
        )
    result.sort(key=lambda item: (-(item["rows"] or 0), str(item["bucket"])))
    return result


def _candidate_coverage(candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    conviction_cfg = load_conviction_config()
    status_counts: dict[str, int] = {}
    pattern_counts: dict[str, int] = {}
    confluence_score_buckets: dict[str, int] = {}
    conviction_score_buckets: dict[str, int] = {}
    probability_buckets: dict[str, int] = {}
    probability_source_counts: dict[str, int] = {}
    confluence_scores: list[float] = []
    conviction_scores: list[float] = []
    probabilities: list[float] = []
    proven_good = 0
    proven_bad = 0
    rows_with_forward_outcome = 0
    rows_with_forward_mfe = 0
    rows_with_confluence_score = 0
    rows_with_conviction_score = 0
    rows_with_probability_pct = 0
    conviction_score_ready_rows = 0
    conviction_probability_ready_rows = 0
    conviction_candidate_rows = 0
    top_missed: list[dict[str, Any]] = []

    for row in candidate_rows:
        status = _bucket(row, "candidate_status")
        status_counts[status] = status_counts.get(status, 0) + 1
        payload = _load_json(row.get("candidate_json"))
        candidate_payload = _candidate_payload(payload)
        pattern = (
            candidate_payload.get("symbol_pattern")
            or payload.get("symbol_pattern")
            or _bucket(row, "setup_label")
        )
        pattern_counts[str(pattern)] = pattern_counts.get(str(pattern), 0) + 1

        confluence_score = _float(
            _candidate_value(row, payload, candidate_payload, "confluence_score")
        )
        conviction_score = _float(
            _candidate_value(row, payload, candidate_payload, "conviction_score")
        )
        probability_pct = _float(
            _candidate_value(row, payload, candidate_payload, "probability_pct")
        )
        probability_source = str(
            _candidate_value(row, payload, candidate_payload, "probability_source") or "missing"
        )
        normalized_probability_source = probability_source.strip().lower()
        confluence_score_buckets[_score_bucket(confluence_score)] = (
            confluence_score_buckets.get(_score_bucket(confluence_score), 0) + 1
        )
        conviction_score_buckets[_score_bucket(conviction_score)] = (
            conviction_score_buckets.get(_score_bucket(conviction_score), 0) + 1
        )
        probability_buckets[_probability_bucket(probability_pct)] = (
            probability_buckets.get(_probability_bucket(probability_pct), 0) + 1
        )
        probability_source_counts[probability_source] = (
            probability_source_counts.get(probability_source, 0) + 1
        )
        if confluence_score is not None:
            rows_with_confluence_score += 1
            confluence_scores.append(confluence_score)
        if conviction_score is not None:
            rows_with_conviction_score += 1
            conviction_scores.append(conviction_score)
        if probability_pct is not None:
            rows_with_probability_pct += 1
            probabilities.append(probability_pct)

        score_ready = conviction_score is not None and conviction_score >= float(
            conviction_cfg.min_score
        )
        probability_threshold = (
            float(conviction_cfg.min_system_probability_pct)
            if normalized_probability_source in SYSTEM_PROBABILITY_SOURCES
            else float(conviction_cfg.min_probability_pct)
        )
        probability_ready = probability_pct is not None and probability_pct >= probability_threshold
        if score_ready:
            conviction_score_ready_rows += 1
        if probability_ready:
            conviction_probability_ready_rows += 1
        if score_ready and probability_ready:
            conviction_candidate_rows += 1

        forward_return = _candidate_return(payload)
        forward_mfe = _candidate_mfe(payload)
        if forward_return is not None:
            rows_with_forward_outcome += 1
            if forward_return > 0:
                proven_good += 1
            else:
                proven_bad += 1
        if forward_mfe is not None:
            rows_with_forward_mfe += 1
            if row.get("candidate_status") != "taken" and forward_mfe > 0:
                top_missed.append(
                    {
                        "symbol": row.get("symbol"),
                        "candidate_ts": row.get("candidate_ts"),
                        "candidate_status": row.get("candidate_status"),
                        "score": row.get("score"),
                        "confluence_score": (
                            round(confluence_score, 4) if confluence_score is not None else None
                        ),
                        "conviction_score": (
                            round(conviction_score, 4) if conviction_score is not None else None
                        ),
                        "probability_pct": (
                            round(probability_pct, 4) if probability_pct is not None else None
                        ),
                        "probability_source": (
                            probability_source if probability_source != "missing" else None
                        ),
                        "threshold_distance": row.get("threshold_distance"),
                        "pattern": pattern,
                        "forward_mfe_pct": round(forward_mfe, 4),
                        "forward_return_pct": forward_return,
                        "reason": row.get("reason"),
                    }
                )

    top_missed.sort(
        key=lambda item: (
            -float(item.get("forward_mfe_pct") or 0.0),
            str(item.get("candidate_ts") or ""),
        )
    )
    return {
        "rows": len(candidate_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "pattern_counts": dict(
            sorted(pattern_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "rows_with_forward_outcome": rows_with_forward_outcome,
        "rows_with_forward_mfe": rows_with_forward_mfe,
        "rows_with_confluence_score": rows_with_confluence_score,
        "rows_with_conviction_score": rows_with_conviction_score,
        "rows_with_probability_pct": rows_with_probability_pct,
        "avg_confluence_score": _mean(confluence_scores),
        "avg_conviction_score": _mean(conviction_scores),
        "avg_probability_pct": _mean(probabilities),
        "confluence_score_buckets": dict(sorted(confluence_score_buckets.items())),
        "conviction_score_buckets": dict(sorted(conviction_score_buckets.items())),
        "probability_buckets": dict(sorted(probability_buckets.items())),
        "probability_source_counts": dict(sorted(probability_source_counts.items())),
        "conviction_gate_config": {
            "min_score": float(conviction_cfg.min_score),
            "min_probability_pct": float(conviction_cfg.min_probability_pct),
            "min_system_probability_pct": float(conviction_cfg.min_system_probability_pct),
            "require_probability": bool(conviction_cfg.require_probability),
        },
        "conviction_score_ready_rows": conviction_score_ready_rows,
        "conviction_probability_ready_rows": conviction_probability_ready_rows,
        "conviction_candidate_rows": conviction_candidate_rows,
        "conviction_candidate_rate": _rate(conviction_candidate_rows, len(candidate_rows)),
        "proven_good": proven_good,
        "proven_bad": proven_bad,
        "forward_outcome_coverage_rate": _rate(rows_with_forward_outcome, len(candidate_rows)),
        "forward_mfe_coverage_rate": _rate(rows_with_forward_mfe, len(candidate_rows)),
        "top_missed_by_mfe": top_missed[:15],
    }


def _bar_pattern_evidence(bar_pattern_rows: list[dict[str, Any]]) -> dict[str, Any]:
    opportunity_counts: dict[str, int] = {}
    pattern_counts: dict[str, int] = {}
    runtime_effects: dict[str, int] = {}
    symbols: set[str] = set()
    rows_with_forward_outcome = 0
    rows_with_forward_mfe = 0
    rows_with_opportunity_label = 0
    long_scores: list[float] = []
    sell_scores: list[float] = []
    forward_returns_by_opportunity: dict[str, list[float]] = {}
    triple_barrier_counts: dict[str, int] = {}
    triple_barrier_returns: dict[str, list[float]] = {}
    trend_scan_counts: dict[str, int] = {}
    trend_scan_returns: dict[str, list[float]] = {}
    cvd_divergence_counts: dict[str, int] = {}
    rows_with_order_flow = 0
    rows_with_fractional_memory = 0
    buy_window_forward_returns: list[float] = []
    sell_avoid_forward_returns: list[float] = []
    buy_windows_with_positive_mfe = 0
    sell_avoid_windows_with_negative_return = 0
    top_buy_windows: list[dict[str, Any]] = []
    top_sell_or_avoid_windows: list[dict[str, Any]] = []

    for row in bar_pattern_rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)

        pattern = _bucket(row, "pattern_label")
        pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        action = _bucket(row, "opportunity_action")
        quality = _bucket(row, "opportunity_quality")
        opportunity_key = f"{action}|{quality}"
        opportunity_counts[opportunity_key] = opportunity_counts.get(opportunity_key, 0) + 1
        if action != "unknown" or quality != "unknown":
            rows_with_opportunity_label += 1

        runtime_effect = _bucket(row, "runtime_effect")
        runtime_effects[runtime_effect] = runtime_effects.get(runtime_effect, 0) + 1

        forward_return = _float(row.get("forward_return_pct"))
        forward_mfe = _float(row.get("forward_mfe_pct"))
        forward_mae = _float(row.get("forward_mae_pct"))
        long_score = _float(row.get("long_opportunity_score"))
        sell_score = _float(row.get("sell_opportunity_score"))
        triple_barrier_label = row.get("triple_barrier_label")
        triple_barrier_reason = _bucket(row, "triple_barrier_reason")
        trend_scan_label = row.get("trend_scan_label")
        trend_scan_reason = _bucket(row, "trend_scan_reason")
        cvd_divergence_label = _bucket(row, "cvd_divergence_label")
        if cvd_divergence_label != "unknown":
            cvd_divergence_counts[cvd_divergence_label] = (
                cvd_divergence_counts.get(cvd_divergence_label, 0) + 1
            )
        if row.get("cvd_price_corr_20") is not None or row.get("vpin_toxicity_20") is not None:
            rows_with_order_flow += 1
        if row.get("fractional_diff_zscore_20") is not None:
            rows_with_fractional_memory += 1
        if triple_barrier_label is not None:
            triple_key = f"{int(float(triple_barrier_label))}|{triple_barrier_reason}"
            triple_barrier_counts[triple_key] = triple_barrier_counts.get(triple_key, 0) + 1
            if forward_return is not None:
                triple_barrier_returns.setdefault(triple_key, []).append(forward_return)
        if trend_scan_label is not None:
            trend_key = f"{int(float(trend_scan_label))}|{trend_scan_reason}"
            trend_scan_counts[trend_key] = trend_scan_counts.get(trend_key, 0) + 1
            if forward_return is not None:
                trend_scan_returns.setdefault(trend_key, []).append(forward_return)

        if forward_return is not None:
            rows_with_forward_outcome += 1
            forward_returns_by_opportunity.setdefault(opportunity_key, []).append(forward_return)
        if forward_mfe is not None:
            rows_with_forward_mfe += 1
        if long_score is not None:
            long_scores.append(long_score)
        if sell_score is not None:
            sell_scores.append(sell_score)

        item = {
            "symbol": symbol,
            "bar_timestamp": row.get("bar_timestamp"),
            "timeframe": row.get("timeframe"),
            "pattern_label": pattern,
            "opportunity_action": action,
            "opportunity_quality": quality,
            "long_opportunity_score": round(long_score, 4) if long_score is not None else None,
            "sell_opportunity_score": round(sell_score, 4) if sell_score is not None else None,
            "forward_return_pct": round(forward_return, 4) if forward_return is not None else None,
            "forward_mfe_pct": round(forward_mfe, 4) if forward_mfe is not None else None,
            "forward_mae_pct": round(forward_mae, 4) if forward_mae is not None else None,
            "triple_barrier_label": (
                int(float(triple_barrier_label)) if triple_barrier_label is not None else None
            ),
            "triple_barrier_reason": triple_barrier_reason,
            "triple_barrier_bars_to_event": row.get("triple_barrier_bars_to_event"),
            "trend_scan_label": (
                int(float(trend_scan_label)) if trend_scan_label is not None else None
            ),
            "trend_scan_tstat": row.get("trend_scan_tstat"),
            "trend_scan_bars": row.get("trend_scan_bars"),
            "cvd_divergence_label": cvd_divergence_label,
            "vpin_toxicity_20": row.get("vpin_toxicity_20"),
            "fractional_diff_zscore_20": row.get("fractional_diff_zscore_20"),
        }
        if action in {"buy_candidate", "long_candidate"} and long_score is not None:
            top_buy_windows.append(item)
            if forward_return is not None:
                buy_window_forward_returns.append(forward_return)
            if forward_mfe is not None and forward_mfe > 0.50:
                buy_windows_with_positive_mfe += 1
        if action == "sell_or_avoid_candidate" and sell_score is not None:
            top_sell_or_avoid_windows.append(item)
            if forward_return is not None:
                sell_avoid_forward_returns.append(forward_return)
                if forward_return < 0:
                    sell_avoid_windows_with_negative_return += 1

    top_buy_windows.sort(
        key=lambda item: (
            -float(item.get("long_opportunity_score") or 0.0),
            str(item.get("bar_timestamp") or ""),
        )
    )
    top_sell_or_avoid_windows.sort(
        key=lambda item: (
            -float(item.get("sell_opportunity_score") or 0.0),
            str(item.get("bar_timestamp") or ""),
        )
    )

    opportunity_expectancy = []
    for opportunity, values in forward_returns_by_opportunity.items():
        opportunity_expectancy.append(
            {
                "opportunity": opportunity,
                "rows": len(values),
                "win_rate": _rate(sum(1 for value in values if value > 0), len(values)),
                "avg_forward_return_pct": _mean(values),
            }
        )
    opportunity_expectancy.sort(key=lambda item: (-(item["rows"] or 0), item["opportunity"]))

    triple_barrier_expectancy = []
    for label, values in triple_barrier_returns.items():
        triple_barrier_expectancy.append(
            {
                "triple_barrier": label,
                "rows": len(values),
                "win_rate": _rate(sum(1 for value in values if value > 0), len(values)),
                "avg_forward_return_pct": _mean(values),
            }
        )
    triple_barrier_expectancy.sort(key=lambda item: (-(item["rows"] or 0), item["triple_barrier"]))

    trend_scan_expectancy = []
    for label, values in trend_scan_returns.items():
        trend_scan_expectancy.append(
            {
                "trend_scan": label,
                "rows": len(values),
                "win_rate": _rate(sum(1 for value in values if value > 0), len(values)),
                "avg_forward_return_pct": _mean(values),
            }
        )
    trend_scan_expectancy.sort(key=lambda item: (-(item["rows"] or 0), item["trend_scan"]))

    return {
        "rows": len(bar_pattern_rows),
        "symbols": len(symbols),
        "rows_with_forward_outcome": rows_with_forward_outcome,
        "rows_with_forward_mfe": rows_with_forward_mfe,
        "rows_with_opportunity_label": rows_with_opportunity_label,
        "forward_outcome_coverage_rate": _rate(rows_with_forward_outcome, len(bar_pattern_rows)),
        "opportunity_label_coverage_rate": _rate(
            rows_with_opportunity_label, len(bar_pattern_rows)
        ),
        "order_flow_coverage_rate": _rate(rows_with_order_flow, len(bar_pattern_rows)),
        "fractional_memory_coverage_rate": _rate(
            rows_with_fractional_memory, len(bar_pattern_rows)
        ),
        "avg_long_opportunity_score": _mean(long_scores),
        "avg_sell_opportunity_score": _mean(sell_scores),
        "buy_window_rows_with_forward_return": len(buy_window_forward_returns),
        "buy_window_win_rate": _rate(
            sum(1 for value in buy_window_forward_returns if value > 0),
            len(buy_window_forward_returns),
        ),
        "buy_window_avg_forward_return_pct": _mean(buy_window_forward_returns),
        "buy_windows_with_positive_mfe": buy_windows_with_positive_mfe,
        "sell_avoid_rows_with_forward_return": len(sell_avoid_forward_returns),
        "sell_avoid_correct_direction_rate": _rate(
            sell_avoid_windows_with_negative_return,
            len(sell_avoid_forward_returns),
        ),
        "sell_avoid_avg_forward_return_pct": _mean(sell_avoid_forward_returns),
        "pattern_counts": dict(
            sorted(pattern_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "opportunity_counts": dict(
            sorted(opportunity_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "triple_barrier_counts": dict(
            sorted(triple_barrier_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "trend_scan_counts": dict(
            sorted(trend_scan_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "cvd_divergence_counts": dict(
            sorted(cvd_divergence_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "runtime_effects": dict(sorted(runtime_effects.items())),
        "opportunity_expectancy": opportunity_expectancy,
        "triple_barrier_expectancy": triple_barrier_expectancy,
        "trend_scan_expectancy": trend_scan_expectancy,
        "top_buy_windows": top_buy_windows[:15],
        "top_sell_or_avoid_windows": top_sell_or_avoid_windows[:15],
    }


def build_pattern_learning_inputs_payload(
    matched_rows: Iterable[dict[str, Any]],
    candidate_rows: Iterable[dict[str, Any]],
    bar_pattern_rows: Iterable[dict[str, Any]] | None = None,
) -> PatternLearningInputsPayload:
    matched = [dict(row) for row in matched_rows]
    candidates = [dict(row) for row in candidate_rows]
    bar_patterns = [dict(row) for row in (bar_pattern_rows or [])]

    for row in matched:
        row["trade_quality"] = _trade_quality(row)

    outcome_rows = [row for row in matched if _float(row.get("realized_pnl_pct")) is not None]
    mfe_rows = [row for row in matched if _float(row.get("mfe_pct")) is not None]
    capture_rows = [row for row in matched if _float(row.get("capture_ratio")) is not None]
    pattern_context_rows = [
        row
        for row in matched
        if any(
            row.get(key) not in (None, "", "unknown")
            for key in (
                "setup_policy_action",
                "setup_label",
                "ml_prediction_bucket",
                "session_trend_label",
                "buy_opportunity_recommendation",
            )
        )
    ]
    fully_integrated_rows = [
        row
        for row in matched
        if _float(row.get("realized_pnl_pct")) is not None
        and _float(row.get("mfe_pct")) is not None
        and row.get("setup_policy_action") not in (None, "", "unknown")
        and row.get("ml_prediction_bucket") not in (None, "", "unknown")
        and row.get("session_trend_label") not in (None, "", "unknown")
    ]
    quality_counts: dict[str, int] = {}
    for row in matched:
        quality = str(row["trade_quality"])
        quality_counts[quality] = quality_counts.get(quality, 0) + 1

    candidate_coverage = _candidate_coverage(candidates)
    bar_pattern_evidence = _bar_pattern_evidence(bar_patterns)
    learning_actions = []
    if matched and len(fully_integrated_rows) < len(matched):
        learning_actions.append(
            "fill missing MFE/prediction/session context on matched trades before model training"
        )
    if candidates and not candidate_coverage["rows_with_forward_outcome"]:
        learning_actions.append(
            "backfill forward outcomes for candidate_universe rows to learn missed buys"
        )
    if not matched:
        learning_actions.append(
            "no matched trades available for executed buy/sell pattern learning"
        )
    if not candidates:
        learning_actions.append(
            "no candidate_universe rows available for missed-opportunity learning"
        )
    if bar_patterns and not bar_pattern_evidence["rows_with_opportunity_label"]:
        learning_actions.append(
            "rerun bar-pattern backfill to populate hindsight buy/sell opportunity labels"
        )
    if (
        bar_pattern_evidence["buy_window_rows_with_forward_return"]
        and (bar_pattern_evidence["buy_window_win_rate"] or 0.0) < 0.50
    ):
        learning_actions.append(
            "review buy-window pattern thresholds; current buy-window win rate is below 50%"
        )
    if (
        bar_pattern_evidence["sell_avoid_rows_with_forward_return"]
        and (bar_pattern_evidence["sell_avoid_correct_direction_rate"] or 0.0) < 0.50
    ):
        learning_actions.append(
            "review sell/avoid pattern thresholds; current avoid windows are not consistently followed by weakness"
        )
    if not bar_patterns:
        learning_actions.append(
            "no bar_pattern_features rows available for EFI/PVT pattern learning"
        )

    summary = {
        "report_version": PATTERN_LEARNING_INPUTS_VERSION,
        "runtime_effect": PATTERN_LEARNING_RUNTIME_EFFECT,
        "matched_trades": len(matched),
        "matched_with_realized_outcome": len(outcome_rows),
        "matched_with_mfe": len(mfe_rows),
        "matched_with_capture_ratio": len(capture_rows),
        "matched_with_pattern_context": len(pattern_context_rows),
        "fully_integrated_pattern_outcome_rows": len(fully_integrated_rows),
        "candidate_rows": len(candidates),
        "candidate_rows_with_forward_outcome": candidate_coverage["rows_with_forward_outcome"],
        "candidate_rows_with_forward_mfe": candidate_coverage["rows_with_forward_mfe"],
        "candidate_rows_with_confluence_score": candidate_coverage["rows_with_confluence_score"],
        "candidate_rows_with_conviction_score": candidate_coverage["rows_with_conviction_score"],
        "candidate_rows_with_probability_pct": candidate_coverage["rows_with_probability_pct"],
        "conviction_candidate_rows": candidate_coverage["conviction_candidate_rows"],
        "bar_pattern_rows": len(bar_patterns),
        "bar_pattern_rows_with_forward_outcome": bar_pattern_evidence["rows_with_forward_outcome"],
        "bar_pattern_rows_with_opportunity_label": bar_pattern_evidence[
            "rows_with_opportunity_label"
        ],
        "quality_counts": dict(sorted(quality_counts.items())),
        "authority_ready": False,
        "authority_note": "diagnostic only; cannot approve, block, size, or execute trades",
    }

    return PatternLearningInputsPayload(
        summary=summary,
        executed_trade_quality=matched,
        expectancy_by_dimension={
            "trade_quality": _expectancy(matched, "trade_quality"),
            "setup_policy_action": _expectancy(matched, "setup_policy_action"),
            "ml_prediction_bucket": _expectancy(matched, "ml_prediction_bucket"),
            "session_trend_label": _expectancy(matched, "session_trend_label"),
            "buy_opportunity_recommendation": _expectancy(
                matched, "buy_opportunity_recommendation"
            ),
        },
        candidate_label_coverage=candidate_coverage,
        bar_pattern_evidence=bar_pattern_evidence,
        learning_actions=learning_actions,
    )
