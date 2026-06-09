"""Normalize intelligence surfaces into one adjudication object."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Direction = Literal["support", "neutral", "caution", "avoid"]
Confidence = Literal["low", "medium", "high"]
Freshness = Literal["fresh", "stale", "missing"]
RecommendedEffect = Literal["observe", "size_down", "block", "approve", "increase_size"]


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


@dataclass(frozen=True)
class ModelAdjudication:
    direction: Direction
    confidence: Confidence
    freshness: Freshness
    sample_size: int | None
    calibrated_win_prob: float | None
    expected_value_pct: float | None
    uncertainty: float | None
    recommended_effect: RecommendedEffect
    max_size_pct: float | None
    reasons: list[str] = field(default_factory=list)
    supports: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_model_adjudication(
    *,
    account_state: dict[str, Any],
    intelligence_context: dict[str, Any] | None = None,
) -> ModelAdjudication:
    intelligence_context = intelligence_context or {}
    setup = account_state.get("setup_quality") or {}
    opportunity = account_state.get("buy_opportunity") or {}
    prediction = (
        account_state.get("prediction_gate") or intelligence_context.get("prediction") or {}
    )
    session = account_state.get("session_momentum_gate") or {}
    execution = account_state.get("execution_quality") or {}

    setup_score = _float(setup.get("score"))
    buy_score = _float(opportunity.get("buy_opportunity_score"))
    pred_score = _float(prediction.get("prediction_score") or prediction.get("ml_prediction_score"))
    sample_size_raw = prediction.get("prediction_sample_size") or prediction.get("sample_size")
    try:
        sample_size = int(sample_size_raw) if sample_size_raw is not None else None
    except Exception:
        sample_size = None

    supports: list[str] = []
    risks: list[str] = []
    reasons: list[str] = []
    if setup_score is not None:
        reasons.append(f"setup_score={setup_score}")
        (supports if setup_score >= 78 else risks if setup_score < 55 else reasons).append(
            "setup_score_signal"
        )
    if buy_score is not None:
        reasons.append(f"buy_opportunity_score={buy_score}")
        (supports if buy_score >= 10 else risks if buy_score < 5 else reasons).append(
            "buy_opportunity_signal"
        )
    if pred_score is not None:
        reasons.append(f"prediction_score={pred_score}")
        (supports if pred_score >= 55 else risks).append("prediction_score_signal")
    if str(session.get("severity") or "").lower() in {"block", "hard_block"}:
        risks.append("session_hard_block")
    elif str(session.get("severity") or "").lower() in {"pass", "supportive"}:
        supports.append("session_supportive")
    if str(execution.get("decision") or "").lower() == "block":
        risks.append("execution_block")

    if any(item in risks for item in ("session_hard_block", "execution_block")):
        direction: Direction = "avoid"
        effect: RecommendedEffect = "block"
    elif len(supports) >= 3 and not risks:
        direction = "support"
        effect = "approve"
    elif len(risks) >= 2:
        direction = "avoid"
        effect = "block"
    elif risks:
        direction = "caution"
        effect = "size_down"
    else:
        direction = "neutral"
        effect = "observe"

    confidence: Confidence = "high" if len(supports) >= 3 else "medium" if supports else "low"
    freshness: Freshness = "fresh"
    if prediction.get("is_stale") is True or account_state.get("is_stale") is True:
        freshness = "stale"
    elif not any((setup, opportunity, prediction, session)):
        freshness = "missing"

    calibrated_win_prob = None
    if pred_score is not None:
        calibrated_win_prob = max(0.0, min(1.0, pred_score / 100.0))
    expected_value = _float((account_state.get("utility_estimate") or {}).get("expected_value_pct"))
    uncertainty = (
        None
        if calibrated_win_prob is None
        else round(1.0 - abs(calibrated_win_prob - 0.5) * 2.0, 6)
    )
    max_size = _float(opportunity.get("max_position_size_pct")) or _float(
        account_state.get("max_position_size_pct_override")
    )
    return ModelAdjudication(
        direction=direction,
        confidence=confidence,
        freshness=freshness,
        sample_size=sample_size,
        calibrated_win_prob=calibrated_win_prob,
        expected_value_pct=expected_value,
        uncertainty=uncertainty,
        recommended_effect=effect,
        max_size_pct=max_size,
        reasons=reasons[:10],
        supports=supports[:10],
        risks=risks[:10],
    )
