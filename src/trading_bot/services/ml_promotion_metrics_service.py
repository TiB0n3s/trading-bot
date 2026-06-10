"""Measured ML promotion metrics from replay and lifecycle evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.lifecycle_analysis_service import LifecycleAnalysisService

from ml_platform.config import DEFAULT_DB_PATH
from ml_platform.lifecycle import REQUIRED_PROMOTION_METRICS
from ml_platform.replay import replay_decisions_v1

PROMOTION_METRICS_VERSION = "ml_promotion_metrics_v1"
MIN_EXPECTED_VALUE_FOR_PAPER_AUTHORITY = 0.0
MIN_PROFIT_FACTOR_FOR_PAPER_AUTHORITY = 1.05
MAX_BRIER_FOR_PAPER_AUTHORITY = 0.25
MAX_CALIBRATION_ERROR_FOR_PAPER_AUTHORITY = 0.20
MIN_STABILITY_SCORE_FOR_PAPER_AUTHORITY = 0.40


@dataclass(frozen=True)
class PromotionMetricsConfig:
    start_date: str
    end_date: str
    db_path: Path | str = DEFAULT_DB_PATH
    friction_bps: float = 10.0
    min_rows_for_stability: int = 3


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    except Exception:
        return None


def _mean(values: list[float]) -> float | None:
    return round(mean(values), 6) if values else None


def _safe_div(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _outcome_pct(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        return _float(row.get("realized_return_pct"))
    for key in ("rejected_return_60m", "rejected_return_30m", "rejected_return_eod"):
        value = _float(row.get(key))
        if value is not None:
            return value
    return None


def _mfe_pct(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        value = _float(row.get("mfe_pct"))
        if value is not None:
            return value
        outcome = _outcome_pct(row)
        return max(0.0, outcome) if outcome is not None else None
    return _float(row.get("rejected_max_favorable_60m"))


def _mae_pct(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        value = _float(row.get("max_adverse_excursion_pct"))
        if value is not None:
            return value
        outcome = _outcome_pct(row)
        return min(0.0, outcome) if outcome is not None else None
    return _float(row.get("rejected_max_adverse_60m"))


def _capture_ratio(row: dict[str, Any]) -> float | None:
    value = _float(row.get("capture_ratio"))
    if value is not None:
        return value
    if not row.get("approved"):
        return None
    outcome = _outcome_pct(row)
    mfe = _mfe_pct(row)
    if outcome is None or mfe is None or mfe <= 0:
        return 0.0 if outcome is not None else None
    return max(0.0, min(1.0, outcome / mfe))


def _prediction_probability(row: dict[str, Any]) -> float | None:
    for key in ("prediction_score", "setup_score", "session_trend_score"):
        value = _float(row.get(key))
        if value is None:
            continue
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))
    return None


def _brier_and_calibration(rows: list[dict[str, Any]]) -> tuple[float | None, float | None, int]:
    scored: list[tuple[float, int]] = []
    for row in rows:
        outcome = _outcome_pct(row)
        prob = _prediction_probability(row)
        if outcome is None or prob is None:
            continue
        scored.append((prob, 1 if outcome > 0 else 0))
    if not scored:
        return None, None, 0
    brier = mean((prob - actual) ** 2 for prob, actual in scored)
    bins: dict[int, list[tuple[float, int]]] = {}
    for prob, actual in scored:
        bins.setdefault(min(9, int(prob * 10)), []).append((prob, actual))
    ece = 0.0
    total = len(scored)
    for bucket in bins.values():
        confidence = mean(prob for prob, _ in bucket)
        accuracy = mean(actual for _, actual in bucket)
        ece += (len(bucket) / total) * abs(confidence - accuracy)
    return round(brier, 6), round(ece, 6), len(scored)


def _profit_factor(outcomes: list[float]) -> float | None:
    gains = sum(value for value in outcomes if value > 0)
    losses = abs(sum(value for value in outcomes if value < 0))
    if gains == 0 and losses == 0:
        return None
    if losses == 0:
        return round(gains, 6)
    return round(gains / losses, 6)


def _max_drawdown(outcomes: list[float]) -> float | None:
    if not outcomes:
        return None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in outcomes:
        equity += value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return round(max_dd, 6)


def _stability_score(
    rows: list[dict[str, Any]],
    group_key: str,
    *,
    min_rows: int,
) -> dict[str, Any]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        outcome = _outcome_pct(row)
        if outcome is None:
            continue
        key = str(row.get(group_key) or "unknown")
        grouped.setdefault(key, []).append(outcome)
    eligible = {key: values for key, values in grouped.items() if len(values) >= min_rows}
    group_ev = {key: round(mean(values), 6) for key, values in sorted(eligible.items())}
    if len(group_ev) < 2:
        return {
            "score": None,
            "groups": group_ev,
            "eligible_group_count": len(group_ev),
            "status": "insufficient_group_coverage",
        }
    values = list(group_ev.values())
    dispersion = pstdev(values)
    score = max(0.0, min(1.0, 1.0 - dispersion / max(1.0, abs(mean(values)) + 1.0)))
    return {
        "score": round(score, 6),
        "groups": group_ev,
        "eligible_group_count": len(group_ev),
        "status": "measured",
    }


def _time_bucket(row: dict[str, Any]) -> str:
    hour = str(row.get("decision_hour") or "unknown")
    if hour in {"09", "10"}:
        return "open"
    if hour in {"11", "12", "13"}:
        return "midday"
    if hour in {"14", "15"}:
        return "close"
    return "unknown"


def build_ml_promotion_metrics_payload(config: PromotionMetricsConfig) -> dict[str, Any]:
    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(config.db_path)).payload(
        start_date=config.start_date,
        end_date=config.end_date,
    )
    rows = lifecycle.rows
    outcome_rows = [row for row in rows if _outcome_pct(row) is not None]
    outcomes = [_outcome_pct(row) for row in outcome_rows]
    outcomes = [value for value in outcomes if value is not None]

    approved_losses = [
        abs(value)
        for row in outcome_rows
        if row.get("approved") and (value := _outcome_pct(row)) is not None and value < 0
    ]
    rejected_winners = [
        value
        for row in outcome_rows
        if not row.get("approved") and (value := _outcome_pct(row)) is not None and value > 0
    ]
    approved_loser_count = len(approved_losses)

    replay = replay_decisions_v1(
        start_date=config.start_date,
        end_date=config.end_date,
        db_path=config.db_path,
        friction_bps=config.friction_bps,
    )
    changed_to_block = int(replay.get("changed_to_block") or 0)
    avoided_losers = int(replay.get("avoided_losers") or 0)
    avoided_loser_precision = _safe_div(avoided_losers, changed_to_block)
    if avoided_loser_precision is None:
        avoided_loser_precision = 0.0
    avoided_loser_recall = _safe_div(avoided_losers, approved_loser_count)
    if avoided_loser_recall is None:
        avoided_loser_recall = 0.0

    brier, calibration_error, calibrated_rows = _brier_and_calibration(outcome_rows)
    mfe_values = [_mfe_pct(row) for row in outcome_rows]
    mfe_values = [value for value in mfe_values if value is not None]
    mae_values = [_mae_pct(row) for row in outcome_rows]
    mae_values = [value for value in mae_values if value is not None]
    capture_values = [
        value
        for row in outcome_rows
        if row.get("approved") and (value := _capture_ratio(row)) is not None
    ]

    symbol_stability = _stability_score(
        outcome_rows,
        "symbol",
        min_rows=config.min_rows_for_stability,
    )
    regime_stability = _stability_score(
        outcome_rows,
        "market_regime",
        min_rows=config.min_rows_for_stability,
    )
    time_rows = [{**row, "time_bucket": _time_bucket(row)} for row in outcome_rows]
    time_stability = _stability_score(
        time_rows,
        "time_bucket",
        min_rows=config.min_rows_for_stability,
    )

    metrics = {
        "expected_value_per_decision": _mean(outcomes),
        "false_positive_cost": _mean(approved_losses) or 0.0,
        "false_negative_opportunity_cost": _mean(rejected_winners) or 0.0,
        "avoid_loser_precision": avoided_loser_precision,
        "avoid_loser_recall": avoided_loser_recall,
        "brier_score": brier,
        "calibration_error": calibration_error,
        "profit_factor": _profit_factor(outcomes),
        "max_drawdown_impact": _max_drawdown(outcomes),
        "average_mfe_delta": _mean(mfe_values),
        "average_mae_delta": _mean(mae_values),
        "slippage_adjusted_decision_delta": _float(replay.get("net_simulated_delta_pct")),
        "capture_ratio_improvement": (
            round(mean(capture_values) - 0.5, 6) if capture_values else None
        ),
        "regime_specific_performance": regime_stability,
        "symbol_specific_stability": symbol_stability,
        "time_of_day_stability": time_stability,
    }

    def _metric_ready(key: str) -> bool:
        value = metrics.get(key)
        if value is None:
            return False
        if isinstance(value, dict) and "score" in value:
            return value.get("score") is not None
        return True

    missing = [key for key in REQUIRED_PROMOTION_METRICS if not _metric_ready(key)]
    measured = [key for key in REQUIRED_PROMOTION_METRICS if _metric_ready(key)]
    authority_blockers: list[str] = []
    ev = _float(metrics.get("expected_value_per_decision"))
    if ev is None or ev <= MIN_EXPECTED_VALUE_FOR_PAPER_AUTHORITY:
        authority_blockers.append("expected_value_not_positive")
    profit_factor = _float(metrics.get("profit_factor"))
    if profit_factor is None or profit_factor < MIN_PROFIT_FACTOR_FOR_PAPER_AUTHORITY:
        authority_blockers.append("profit_factor_below_threshold")
    brier = _float(metrics.get("brier_score"))
    if brier is None or brier > MAX_BRIER_FOR_PAPER_AUTHORITY:
        authority_blockers.append("brier_score_above_threshold")
    calibration = _float(metrics.get("calibration_error"))
    if calibration is None or calibration > MAX_CALIBRATION_ERROR_FOR_PAPER_AUTHORITY:
        authority_blockers.append("calibration_error_above_threshold")
    for key in (
        "regime_specific_performance",
        "symbol_specific_stability",
        "time_of_day_stability",
    ):
        value = metrics.get(key)
        score = _float(value.get("score")) if isinstance(value, dict) else None
        if score is None:
            authority_blockers.append(f"{key}:insufficient_coverage")
        elif score < MIN_STABILITY_SCORE_FOR_PAPER_AUTHORITY:
            authority_blockers.append(f"{key}:below_threshold")
    ready_for_monitored_paper_authority = (
        not missing and not authority_blockers and len(outcome_rows) > 0
    )
    authority_recommendation = (
        "monitored_paper_risk_reduction_and_candidate_sizing"
        if ready_for_monitored_paper_authority
        else "bounded_paper_exploration_authority_with_caps"
    )
    return {
        "report_version": PROMOTION_METRICS_VERSION,
        "runtime_effect": "measured_evidence_no_runtime_authority_change",
        "start_date": config.start_date,
        "end_date": config.end_date,
        "friction_bps": config.friction_bps,
        "rows": len(rows),
        "outcome_rows": len(outcome_rows),
        "approved_loser_count": approved_loser_count,
        "rejected_winner_count": len(rejected_winners),
        "calibrated_prediction_rows": calibrated_rows,
        "metrics": metrics,
        "measured_metric_count": len(measured),
        "missing_metrics": missing,
        "ready_for_candidate_registration_metrics": not missing,
        "paper_authority_assessment": {
            "ready_for_monitored_paper_authority": ready_for_monitored_paper_authority,
            "authority_recommendation": authority_recommendation,
            "blockers": authority_blockers,
            "thresholds": {
                "min_expected_value_per_decision": MIN_EXPECTED_VALUE_FOR_PAPER_AUTHORITY,
                "min_profit_factor": MIN_PROFIT_FACTOR_FOR_PAPER_AUTHORITY,
                "max_brier_score": MAX_BRIER_FOR_PAPER_AUTHORITY,
                "max_calibration_error": MAX_CALIBRATION_ERROR_FOR_PAPER_AUTHORITY,
                "min_stability_score": MIN_STABILITY_SCORE_FOR_PAPER_AUTHORITY,
            },
            "allowed_runtime_effect_when_blocked": (
                "ML may reduce size, block weak setups, annotate context, and in paper/dry-run "
                "approve or increase size only through explicit bounded exploration caps. "
                "Cash modes remain excluded."
            ),
        },
        "lifecycle_summary": lifecycle.summary,
        "replay_summary": {
            key: replay.get(key)
            for key in (
                "snapshots_evaluated",
                "changed_decision_count",
                "changed_to_block",
                "changed_to_allow",
                "avoided_losers",
                "missed_winners",
                "recovered_missed_winners",
                "introduced_losers",
                "net_simulated_delta_pct",
                "friction_assumptions",
            )
        },
    }
