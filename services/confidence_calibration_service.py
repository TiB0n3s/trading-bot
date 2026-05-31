"""Calibrated confidence contract for decision sources.

Raw labels such as high/medium/low remain useful operational signals, but they
are not statistical evidence. This module converts raw source labels plus
optional historical bucket stats into a structured, auditable confidence view.
It performs no data access and has no trading authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


RAW_CONFIDENCE_PRIORS = {
    "very_high": 0.68,
    "high": 0.62,
    "medium": 0.54,
    "low": 0.46,
    "very_low": 0.40,
    "none": None,
    "": None,
}


@dataclass(frozen=True)
class SourceCalibrationEstimate:
    source: str
    bucket_key: str
    raw_confidence: str | None
    predicted_win_rate: float | None
    realized_win_rate: float | None
    sample_size: int
    avg_realized_pnl_pct: float | None
    avg_mfe_pct: float | None
    avg_mae_pct: float | None
    precision_by_setup_type: float | None
    precision_by_regime: float | None
    precision_by_time_of_day: float | None
    calibration_error: float | None
    expected_move_r: float | None
    expected_adverse_r: float | None
    quality: str
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CalibratedConfidence:
    primary_source: str
    primary_predicted_win_rate: float | None
    primary_realized_win_rate: float | None
    primary_sample_size: int
    confidence_quality: str
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _raw_prior(raw_confidence: Any) -> float | None:
    return RAW_CONFIDENCE_PRIORS.get(str(raw_confidence or "").strip().lower())


def _quality(sample_size: int, realized_win_rate: float | None) -> str:
    if realized_win_rate is None or sample_size <= 0:
        return "uncalibrated_prior"
    if sample_size >= 50:
        return "high"
    if sample_size >= 20:
        return "medium"
    if sample_size >= 5:
        return "low"
    return "thin_sample"


def _calibration_error(
    predicted_win_rate: float | None,
    realized_win_rate: float | None,
) -> float | None:
    if predicted_win_rate is None or realized_win_rate is None:
        return None
    return round(abs(predicted_win_rate - realized_win_rate), 4)


def _expected_r(avg_realized_pnl_pct: float | None, avg_mae_pct: float | None) -> float | None:
    if avg_realized_pnl_pct is None or avg_mae_pct in (None, 0):
        return None
    adverse = abs(avg_mae_pct)
    if adverse <= 0:
        return None
    return round(avg_realized_pnl_pct / adverse, 4)


def _source_stats(stats: dict[str, Any], source: str, bucket_key: str) -> dict[str, Any]:
    source_block = _dict(stats.get(source))
    by_bucket = _dict(source_block.get("by_bucket"))
    if bucket_key in by_bucket and isinstance(by_bucket[bucket_key], dict):
        return by_bucket[bucket_key]
    return source_block


def _estimate_source(
    *,
    source: str,
    raw_confidence: str | None,
    bucket_key: str,
    stats: dict[str, Any],
) -> SourceCalibrationEstimate:
    source_stats = _source_stats(stats, source, bucket_key)
    sample_size = _int(source_stats.get("sample_size") or source_stats.get("n"))
    realized_win_rate = _float(
        source_stats.get("realized_win_rate")
        or source_stats.get("win_rate")
        or source_stats.get("precision")
    )
    predicted_win_rate = _float(source_stats.get("predicted_win_rate"))
    fallback_reason = None

    if predicted_win_rate is None:
        predicted_win_rate = _raw_prior(raw_confidence)
        if predicted_win_rate is not None:
            fallback_reason = "raw_confidence_prior"
    if realized_win_rate is None:
        fallback_reason = fallback_reason or "missing_realized_calibration"

    avg_realized_pnl_pct = _float(source_stats.get("avg_realized_pnl_pct"))
    avg_mfe_pct = _float(source_stats.get("avg_mfe_pct"))
    avg_mae_pct = _float(source_stats.get("avg_mae_pct"))
    expected_move_r = _float(source_stats.get("expected_move_r"))
    if expected_move_r is None:
        expected_move_r = _expected_r(avg_realized_pnl_pct, avg_mae_pct)
    expected_adverse_r = _float(source_stats.get("expected_adverse_r"))
    if expected_adverse_r is None and avg_mae_pct is not None:
        expected_adverse_r = round(abs(avg_mae_pct), 4)

    return SourceCalibrationEstimate(
        source=source,
        bucket_key=bucket_key,
        raw_confidence=raw_confidence,
        predicted_win_rate=_round(predicted_win_rate),
        realized_win_rate=_round(realized_win_rate),
        sample_size=sample_size,
        avg_realized_pnl_pct=_round(avg_realized_pnl_pct),
        avg_mfe_pct=_round(avg_mfe_pct),
        avg_mae_pct=_round(avg_mae_pct),
        precision_by_setup_type=_round(_float(source_stats.get("precision_by_setup_type"))),
        precision_by_regime=_round(_float(source_stats.get("precision_by_regime"))),
        precision_by_time_of_day=_round(_float(source_stats.get("precision_by_time_of_day"))),
        calibration_error=_calibration_error(predicted_win_rate, realized_win_rate),
        expected_move_r=_round(expected_move_r),
        expected_adverse_r=_round(expected_adverse_r),
        quality=_quality(sample_size, realized_win_rate),
        fallback_reason=fallback_reason,
    )


def _time_of_day_bucket(decision_ts: Any) -> str:
    text = str(decision_ts or "")
    if len(text) < 13:
        return "unknown_time"
    try:
        hour = int(text[11:13])
    except Exception:
        return "unknown_time"
    if hour < 11:
        return "morning"
    if hour < 14:
        return "midday"
    return "late_day"


def build_calibrated_confidence(
    *,
    account_state: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
    calibration_stats: dict[str, Any] | None = None,
) -> CalibratedConfidence:
    """Build calibrated source confidence from runtime context and optional stats."""
    account_state = _dict(account_state)
    context = _dict(context)
    decision = _dict(decision)
    stats = calibration_stats if isinstance(calibration_stats, dict) else _dict(
        account_state.get("calibration_stats")
    )

    setup = _dict(account_state.get("setup_quality") or account_state.get("setup_observation"))
    prediction = _dict(account_state.get("prediction_gate"))
    market_regime = _dict(account_state.get("market_regime"))
    utility = _dict(account_state.get("utility_estimate") or _dict(account_state.get("decision_policy")).get("utility_estimate"))

    setup_label = str(
        setup.get("label") or setup.get("setup_label") or "unknown_setup"
    )
    regime = str(
        market_regime.get("composite_regime")
        or context.get("market_regime")
        or context.get("macro_regime")
        or "unknown_regime"
    )
    time_bucket = _time_of_day_bucket(
        account_state.get("decision_ts") or context.get("decision_ts")
    )

    estimates = [
        _estimate_source(
            source="claude",
            raw_confidence=decision.get("confidence"),
            bucket_key=f"{setup_label}|{regime}|{time_bucket}",
            stats=stats,
        ),
        _estimate_source(
            source="ml_prediction",
            raw_confidence=prediction.get("ml_prediction_confidence"),
            bucket_key=str(prediction.get("ml_prediction_bucket") or "unknown_ml_bucket"),
            stats=stats,
        ),
        _estimate_source(
            source="setup_quality",
            raw_confidence=setup.get("confidence") or setup.get("setup_confidence"),
            bucket_key=f"{setup_label}|{regime}",
            stats=stats,
        ),
        _estimate_source(
            source="utility",
            raw_confidence=utility.get("confidence"),
            bucket_key=str(utility.get("utility_decision") or "unknown_utility"),
            stats=stats,
        ),
    ]

    source_payload = {estimate.source: estimate.to_dict() for estimate in estimates}
    ranked = sorted(
        estimates,
        key=lambda item: (
            item.quality not in {"uncalibrated_prior"},
            item.sample_size,
            item.realized_win_rate is not None,
        ),
        reverse=True,
    )
    primary = ranked[0]
    return CalibratedConfidence(
        primary_source=primary.source,
        primary_predicted_win_rate=primary.predicted_win_rate,
        primary_realized_win_rate=primary.realized_win_rate,
        primary_sample_size=primary.sample_size,
        confidence_quality=primary.quality,
        sources=source_payload,
    )
