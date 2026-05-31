"""Observe-only exit decision quality factors."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExitDecisionQuality:
    exit_pressure_state: str
    trend_deterioration_state: str
    relative_strength_rollover_state: str
    breadth_divergence_state: str
    adverse_volatility_state: str
    target_stop_adaptation_state: str
    time_stop_state: str
    thesis_state: str
    structural_trailing_state: str
    exit_quality_score: float
    recommended_action: str
    inputs: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

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


def _label(value: Any) -> str:
    return str(value or "").strip().lower()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def evaluate_exit_decision_quality(
    *,
    account_state: dict[str, Any] | None = None,
) -> ExitDecisionQuality:
    account_state = _dict(account_state)
    exit_inputs = _dict(account_state.get("exit_decision_inputs"))
    momentum = _dict(account_state.get("momentum"))
    trend = _dict(account_state.get("trend") or account_state.get("trend_context"))
    market_participation = _dict(account_state.get("market_participation"))
    volatility = _dict(account_state.get("volatility_normalization"))
    microstructure = _dict(account_state.get("market_microstructure"))

    trend_slope_change = _float(exit_inputs.get("trend_slope_change_pct"))
    trend_direction = _label(trend.get("direction") or exit_inputs.get("trend_direction"))
    rs_change = _float(exit_inputs.get("relative_strength_change_pct"))
    breadth_change = _float(exit_inputs.get("breadth_change_pct"))
    adverse_vol_expansion = _float(
        exit_inputs.get("adverse_volatility_expansion")
        or exit_inputs.get("adverse_volatility_expansion_ratio")
    )
    unrealized_pnl_pct = _float(exit_inputs.get("unrealized_pnl_pct") or account_state.get("unrealized_pnl_pct"))
    holding_minutes = _float(exit_inputs.get("holding_minutes") or account_state.get("holding_minutes"))
    max_expected_holding_minutes = _float(exit_inputs.get("max_expected_holding_minutes"))
    thesis_invalidated = bool(exit_inputs.get("thesis_invalidated"))
    structure_trail_distance_pct = _float(exit_inputs.get("structure_trail_distance_pct"))
    trailing_stop_distance_pct = _float(exit_inputs.get("trailing_stop_distance_pct"))
    target_adaptation = _label(exit_inputs.get("target_stop_adaptation_state"))
    participation_state = _label(market_participation.get("participation_state"))
    isolated_risk = _label(market_participation.get("isolated_move_risk"))
    chase_risk = _label(volatility.get("chase_risk"))
    reversion_risk = _label(microstructure.get("reversion_risk"))

    score = 0.25
    reasons: list[str] = []

    trend_deterioration_state = "unknown"
    if trend_direction in {"bearish", "down"} or (trend_slope_change is not None and trend_slope_change <= -0.35):
        trend_deterioration_state = "deteriorating"
        score += 0.16
        reasons.append("trend_deteriorating")
    elif trend_direction in {"bullish", "up"} and (trend_slope_change is None or trend_slope_change >= -0.10):
        trend_deterioration_state = "intact"
        score -= 0.04

    relative_strength_rollover_state = "unknown"
    if rs_change is not None:
        if rs_change <= -0.40:
            relative_strength_rollover_state = "rollover"
            score += 0.14
            reasons.append(f"rs_rollover={rs_change:.2f}%")
        elif rs_change >= 0.20:
            relative_strength_rollover_state = "still_leading"
            score -= 0.04

    breadth_divergence_state = "unknown"
    if breadth_change is not None:
        if breadth_change <= -8:
            breadth_divergence_state = "breadth_diverging"
            score += 0.12
            reasons.append(f"breadth_change={breadth_change:.1f}")
        elif breadth_change >= 5:
            breadth_divergence_state = "breadth_confirming"
            score -= 0.03
    if participation_state == "isolated_or_weak" or isolated_risk == "high":
        breadth_divergence_state = "participation_failed"
        score += 0.10
        reasons.append("participation_failed")

    adverse_volatility_state = "unknown"
    if adverse_vol_expansion is not None and adverse_vol_expansion >= 1.35:
        adverse_volatility_state = "expanding_against_position"
        score += 0.12
        reasons.append(f"adverse_vol_expansion={adverse_vol_expansion:.2f}")
    elif chase_risk == "high" or reversion_risk == "high":
        adverse_volatility_state = "reversion_or_chase_risk"
        score += 0.08
        reasons.append("reversion_or_chase_risk")

    target_stop_adaptation_state = target_adaptation or "unknown"
    if target_stop_adaptation_state in {"tighten", "reduce_target", "defensive"}:
        score += 0.06
        reasons.append(f"target_stop_adaptation={target_stop_adaptation_state}")

    time_stop_state = "not_applicable"
    if holding_minutes is not None and max_expected_holding_minutes is not None:
        if holding_minutes >= max_expected_holding_minutes and (unrealized_pnl_pct or 0) <= 0.15:
            time_stop_state = "time_stop_triggered"
            score += 0.11
            reasons.append("time_stop_triggered")
        else:
            time_stop_state = "within_expected_hold"

    thesis_state = "intact"
    if thesis_invalidated:
        thesis_state = "invalidated"
        score += 0.22
        reasons.append("thesis_invalidated")

    structural_trailing_state = "unknown"
    if structure_trail_distance_pct is not None and trailing_stop_distance_pct is not None:
        if trailing_stop_distance_pct > structure_trail_distance_pct * 1.5:
            structural_trailing_state = "trail_too_loose_vs_structure"
            score += 0.08
            reasons.append("trail_too_loose_vs_structure")
        elif trailing_stop_distance_pct <= structure_trail_distance_pct * 1.1:
            structural_trailing_state = "trail_structure_aligned"
            score -= 0.03

    final_score = _clamp(score)
    if final_score >= 0.70:
        exit_pressure_state = "hard_exit_pressure"
        recommended_action = "exit_or_tighten_aggressively"
    elif final_score >= 0.45:
        exit_pressure_state = "moderate_exit_pressure"
        recommended_action = "tighten_or_partial"
    else:
        exit_pressure_state = "low_exit_pressure"
        recommended_action = "hold_with_structure"

    return ExitDecisionQuality(
        exit_pressure_state=exit_pressure_state,
        trend_deterioration_state=trend_deterioration_state,
        relative_strength_rollover_state=relative_strength_rollover_state,
        breadth_divergence_state=breadth_divergence_state,
        adverse_volatility_state=adverse_volatility_state,
        target_stop_adaptation_state=target_stop_adaptation_state,
        time_stop_state=time_stop_state,
        thesis_state=thesis_state,
        structural_trailing_state=structural_trailing_state,
        exit_quality_score=round(final_score, 4),
        recommended_action=recommended_action,
        inputs={
            "trend_slope_change_pct": trend_slope_change,
            "trend_direction": trend_direction or None,
            "relative_strength_change_pct": rs_change,
            "breadth_change_pct": breadth_change,
            "adverse_volatility_expansion": adverse_vol_expansion,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "holding_minutes": holding_minutes,
            "max_expected_holding_minutes": max_expected_holding_minutes,
            "thesis_invalidated": thesis_invalidated,
            "structure_trail_distance_pct": structure_trail_distance_pct,
            "trailing_stop_distance_pct": trailing_stop_distance_pct,
        },
        reasons=reasons[:12],
    )
