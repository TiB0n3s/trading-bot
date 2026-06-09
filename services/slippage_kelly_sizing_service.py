"""Slippage-adjusted fractional Kelly sizing.

This module is a final sizing guard only. It can cap or zero a BUY size when
execution friction erodes expected edge; it cannot approve, loosen, or submit
orders.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from typing import Any

from services.policy_controls import policy_family_enabled

SLIPPAGE_KELLY_VERSION = "slippage_adjusted_kelly_v1"
SLIPPAGE_KELLY_RUNTIME_EFFECT = "size_cap_only_no_approval_authority"


@dataclass(frozen=True)
class SlippageKellyDecision:
    enabled: bool
    runtime_effect: str
    version: str
    model_prob: float | None
    raw_reward_pct: float | None
    raw_risk_pct: float | None
    adjusted_reward_pct: float | None
    adjusted_risk_pct: float | None
    adjusted_risk_reward_ratio: float | None
    predicted_slippage_pct: float | None
    friction_ratio: float | None
    alpha_friction_ratio: float | None
    quote_instability_multiplier: float | None
    liquidity_stress_score: float | None
    liquidity_stress_bucket: str | None
    liquidity_stress_size_multiplier: float | None
    pareto_frontier_selection: dict[str, Any] | None
    kelly_fraction: float | None
    fractional_kelly_pct: float | None
    cap_pct: float | None
    action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
    except Exception:
        return None
    if not math.isfinite(result):
        return None
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _probability_from_state(account_state: dict[str, Any]) -> float | None:
    candidates = [
        _dict(account_state.get("prediction_gate")).get("ml_prediction_score"),
        account_state.get("prediction_score"),
        _dict(account_state.get("prediction")).get("score"),
        _dict(account_state.get("calibrated_confidence")).get("predicted_win_rate"),
        _dict(account_state.get("decision_utility")).get("prob_favorable_move"),
        _dict(account_state.get("utility_estimate")).get("prob_favorable_move"),
    ]
    for value in candidates:
        prob = _float(value)
        if prob is None:
            continue
        if prob > 1.0:
            prob = prob / 100.0
        if 0.0 <= prob <= 1.0:
            return prob
    return None


def _atr_pct_from_state(account_state: dict[str, Any]) -> float | None:
    candidates = [
        account_state.get("atr_20_pct"),
        _dict(account_state.get("volatility_normalization")).get("atr_20_pct"),
        _dict(account_state.get("bar_pattern_features")).get("atr_20_pct"),
        _dict(account_state.get("setup_quality")).get("atr_20_pct"),
        _dict(account_state.get("momentum")).get("atr_20_pct"),
    ]
    for value in candidates:
        atr_pct = _float(value)
        if atr_pct is not None and atr_pct > 0:
            return atr_pct
    return None


def _predicted_slippage_pct(account_state: dict[str, Any]) -> float | None:
    execution_quality = _dict(account_state.get("execution_quality"))
    candidates = [
        execution_quality.get("predicted_slippage_pct"),
        execution_quality.get("slippage_estimate_pct"),
        _dict(account_state.get("slippage_model")).get("predicted_slippage_pct"),
        _dict(account_state.get("execution_slippage")).get("predicted_slippage_pct"),
    ]
    for value in candidates:
        slip = _float(value)
        if slip is not None and slip >= 0:
            return slip
    return None


def _trade_timeout_minutes(account_state: dict[str, Any]) -> float | None:
    features = _dict(account_state.get("bar_pattern_features"))
    candidates = [
        features.get("triple_barrier_timeout_minutes"),
        features.get("triple_barrier_time_out_minutes"),
        features.get("triple_barrier_time_out_bars"),
        features.get("triple_barrier_timeout_bars"),
        account_state.get("triple_barrier_timeout_minutes"),
        account_state.get("expected_holding_minutes"),
    ]
    for value in candidates:
        parsed = _float(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _mae_60m_risk_pct(account_state: dict[str, Any]) -> float | None:
    candidates = [
        account_state.get("expected_mae_60m_pct"),
        account_state.get("max_adverse_60m_pct"),
        _dict(account_state.get("decision_utility")).get("expected_mae_60m_pct"),
        _dict(account_state.get("risk_forecast")).get("expected_mae_60m_pct"),
        _dict(account_state.get("historical_bar_paper_strategy")).get("expected_mae_60m_pct"),
        _dict(account_state.get("bar_pattern_features")).get("expected_mae_60m_pct"),
    ]
    for value in candidates:
        parsed = _float(value)
        if parsed is not None:
            return abs(parsed)
    return None


def _quote_instability_multiplier(account_state: dict[str, Any]) -> tuple[float, str | None]:
    execution_quality = _dict(account_state.get("execution_quality"))
    telemetry = _dict(account_state.get("hardware_telemetry")) or _dict(
        account_state.get("execution_telemetry")
    )
    instability = _float(execution_quality.get("quote_instability_score"))
    cancel_fill = _float(
        execution_quality.get("cancel_fill_ratio")
        or telemetry.get("cancel_fill_ratio")
        or telemetry.get("top_of_book_cancel_fill_ratio")
    )
    quote_change_rate = _float(
        execution_quality.get("quote_change_rate")
        or telemetry.get("quote_change_rate")
        or telemetry.get("top_of_book_quote_change_rate")
    )
    stress = max(
        value
        for value in (
            instability,
            cancel_fill,
            quote_change_rate,
            0.0,
        )
        if value is not None
    )
    if stress >= 0.85:
        return 0.25, f"quote_instability_severe={stress:.2f}"
    if stress >= 0.65:
        return 0.50, f"quote_instability_high={stress:.2f}"
    if stress >= 0.45:
        return 0.75, f"quote_instability_elevated={stress:.2f}"
    return 1.0, None


def _pareto_frontier_selection(
    *,
    requested_size_pct: float,
    kelly_cap_pct: float,
    raw_risk_pct: float,
    friction_ratio: float,
    alpha_friction_ratio: float | None,
    quote_multiplier: float,
    account_state: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    enabled = _env_bool("SLIPPAGE_KELLY_PARETO_SELECTION_ENABLED", True)
    mae_60m = _mae_60m_risk_pct(account_state)
    mae_multiplier = 1.0
    mae_cap_pct = requested_size_pct
    if mae_60m is not None and raw_risk_pct > 0:
        mae_pressure = mae_60m / raw_risk_pct
        if mae_pressure >= 1.50:
            mae_multiplier = 0.25
        elif mae_pressure >= 1.00:
            mae_multiplier = 0.50
        elif mae_pressure >= 0.75:
            mae_multiplier = 0.75
        mae_cap_pct = requested_size_pct * mae_multiplier

    turnover_pressure = alpha_friction_ratio if alpha_friction_ratio is not None else friction_ratio
    turnover_multiplier = 1.0
    if turnover_pressure >= 0.30:
        turnover_multiplier = 0.35
    elif turnover_pressure >= 0.20:
        turnover_multiplier = 0.60
    elif turnover_pressure >= 0.12:
        turnover_multiplier = 0.80
    turnover_multiplier = min(turnover_multiplier, quote_multiplier)
    turnover_cap_pct = requested_size_pct * turnover_multiplier

    objective_caps = {
        "kelly_growth_cap_pct": round(kelly_cap_pct, 4),
        "mae_conservation_cap_pct": round(mae_cap_pct, 4),
        "turnover_cost_cap_pct": round(turnover_cap_pct, 4),
    }
    selected_cap = min(objective_caps.values()) if enabled else kelly_cap_pct
    selected_objective = min(objective_caps, key=objective_caps.get)
    return max(0.0, selected_cap), {
        "enabled": enabled,
        "runtime_effect": "size_cap_only_no_approval_authority",
        "objectives": objective_caps,
        "selected_objective": selected_objective if enabled else "kelly_growth_cap_pct",
        "selected_cap_pct": round(selected_cap, 4) if enabled else round(kelly_cap_pct, 4),
        "mae_60m_risk_pct": round(mae_60m, 4) if mae_60m is not None else None,
        "mae_multiplier": round(mae_multiplier, 4),
        "turnover_pressure": round(turnover_pressure, 4),
        "turnover_multiplier": round(turnover_multiplier, 4),
        "reason": "conservative Pareto edge selected across growth, MAE, and turnover objectives",
    }


def _liquidity_stress_from_state(account_state: dict[str, Any]) -> tuple[float | None, str | None]:
    paper_strategy = _dict(account_state.get("historical_bar_paper_strategy"))
    explicit_score = _float(paper_strategy.get("liquidity_stress_score"))
    explicit_bucket = str(paper_strategy.get("liquidity_stress_bucket") or "").strip().lower()
    if explicit_score is not None:
        bucket = explicit_bucket or _bucket_liquidity_stress(explicit_score)
        return explicit_score, bucket

    bar_features = _dict(account_state.get("bar_pattern_features"))
    execution_quality = _dict(account_state.get("execution_quality"))
    volatility = _dict(account_state.get("volatility_normalization"))
    components: list[float] = []

    vpin = _float(bar_features.get("vpin_toxicity_20"))
    if vpin is not None:
        components.append(max(0.0, min(100.0, vpin * 100.0)))

    spread = _float(bar_features.get("bid_ask_spread_pct")) or _float(
        execution_quality.get("spread_pct")
    )
    if spread is not None:
        components.append(max(0.0, min(100.0, spread * 80.0)))

    slippage = _float(bar_features.get("slippage_estimate_pct")) or _float(
        execution_quality.get("slippage_estimate_pct")
    )
    if slippage is not None:
        components.append(max(0.0, min(100.0, slippage * 120.0)))

    sweep = _float(bar_features.get("liquidity_sweep_risk"))
    if sweep is not None:
        components.append(max(0.0, min(100.0, sweep * 100.0)))

    move_zscore = _float(volatility.get("move_zscore"))
    if move_zscore is not None:
        components.append(max(0.0, min(100.0, abs(move_zscore) * 20.0)))

    if not components:
        return None, None
    score = sum(components) / len(components)
    return score, _bucket_liquidity_stress(score)


def _bucket_liquidity_stress(score: float) -> str:
    if score >= 70:
        return "severe"
    if score >= 45:
        return "elevated"
    if score >= 20:
        return "moderate"
    return "normal"


def _liquidity_stress_multiplier(
    *,
    score: float | None,
    bucket: str | None,
    account_state: dict[str, Any],
) -> tuple[float, str | None]:
    if score is None and not bucket:
        return 1.0, None
    bucket = (bucket or _bucket_liquidity_stress(float(score or 0.0))).lower()
    severe_mult = _env_float("SLIPPAGE_KELLY_LSI_SEVERE_MULT", 0.25)
    elevated_mult = _env_float("SLIPPAGE_KELLY_LSI_ELEVATED_MULT", 0.50)
    moderate_mult = _env_float("SLIPPAGE_KELLY_LSI_MODERATE_MULT", 0.75)
    normal_mult = _env_float("SLIPPAGE_KELLY_LSI_NORMAL_MULT", 1.0)
    toxic_vpin_zero = _env_float("SLIPPAGE_KELLY_TOXIC_VPIN_ZERO_THRESHOLD", 0.95)
    vpin = _float(_dict(account_state.get("bar_pattern_features")).get("vpin_toxicity_20"))
    if vpin is not None and vpin >= toxic_vpin_zero:
        return 0.0, f"toxic_vpin_exceeds_{toxic_vpin_zero:.2f}"
    if bucket == "severe":
        return max(0.0, min(1.0, severe_mult)), "lsi_severe"
    if bucket == "elevated":
        return max(0.0, min(1.0, elevated_mult)), "lsi_elevated"
    if bucket == "moderate":
        return max(0.0, min(1.0, moderate_mult)), "lsi_moderate"
    return max(0.0, min(1.0, normal_mult)), "lsi_normal"


def _decision(
    *,
    enabled: bool,
    action: str,
    reason: str,
    model_prob: float | None = None,
    raw_reward_pct: float | None = None,
    raw_risk_pct: float | None = None,
    adjusted_reward_pct: float | None = None,
    adjusted_risk_pct: float | None = None,
    adjusted_risk_reward_ratio: float | None = None,
    predicted_slippage_pct: float | None = None,
    friction_ratio: float | None = None,
    alpha_friction_ratio: float | None = None,
    quote_instability_multiplier: float | None = None,
    liquidity_stress_score: float | None = None,
    liquidity_stress_bucket: str | None = None,
    liquidity_stress_size_multiplier: float | None = None,
    pareto_frontier_selection: dict[str, Any] | None = None,
    kelly_fraction: float | None = None,
    fractional_kelly_pct: float | None = None,
    cap_pct: float | None = None,
) -> SlippageKellyDecision:
    return SlippageKellyDecision(
        enabled=enabled,
        runtime_effect=SLIPPAGE_KELLY_RUNTIME_EFFECT,
        version=SLIPPAGE_KELLY_VERSION,
        model_prob=round(model_prob, 4) if model_prob is not None else None,
        raw_reward_pct=round(raw_reward_pct, 4) if raw_reward_pct is not None else None,
        raw_risk_pct=round(raw_risk_pct, 4) if raw_risk_pct is not None else None,
        adjusted_reward_pct=(
            round(adjusted_reward_pct, 4) if adjusted_reward_pct is not None else None
        ),
        adjusted_risk_pct=round(adjusted_risk_pct, 4) if adjusted_risk_pct is not None else None,
        adjusted_risk_reward_ratio=(
            round(adjusted_risk_reward_ratio, 4) if adjusted_risk_reward_ratio is not None else None
        ),
        predicted_slippage_pct=(
            round(predicted_slippage_pct, 4) if predicted_slippage_pct is not None else None
        ),
        friction_ratio=round(friction_ratio, 4) if friction_ratio is not None else None,
        alpha_friction_ratio=(
            round(alpha_friction_ratio, 4) if alpha_friction_ratio is not None else None
        ),
        quote_instability_multiplier=(
            round(quote_instability_multiplier, 4)
            if quote_instability_multiplier is not None
            else None
        ),
        liquidity_stress_score=(
            round(liquidity_stress_score, 4) if liquidity_stress_score is not None else None
        ),
        liquidity_stress_bucket=liquidity_stress_bucket,
        liquidity_stress_size_multiplier=(
            round(liquidity_stress_size_multiplier, 4)
            if liquidity_stress_size_multiplier is not None
            else None
        ),
        pareto_frontier_selection=pareto_frontier_selection,
        kelly_fraction=round(kelly_fraction, 4) if kelly_fraction is not None else None,
        fractional_kelly_pct=(
            round(fractional_kelly_pct, 4) if fractional_kelly_pct is not None else None
        ),
        cap_pct=round(cap_pct, 4) if cap_pct is not None else None,
        action=action,
        reason=reason,
    )


def calculate_slippage_adjusted_kelly_cap(
    *,
    account_state: dict[str, Any],
    action: str,
    requested_size_pct: float,
) -> SlippageKellyDecision:
    """Return a size cap from slippage-adjusted Kelly math.

    Units are percentage points of price/account sizing, matching the existing
    execution-quality `slippage_estimate_pct` and `position_size_pct` contract.
    """
    action = (action or "").lower()
    enabled = policy_family_enabled("sizing") and _env_bool("SLIPPAGE_KELLY_SIZING_ENABLED", True)
    if not enabled:
        return _decision(enabled=False, action="none", reason="disabled")
    if action != "buy":
        return _decision(enabled=True, action="none", reason="not_buy")

    requested_size_pct = max(0.0, float(requested_size_pct or 0.0))
    model_prob = _probability_from_state(account_state)
    if model_prob is None:
        return _decision(enabled=True, action="none", reason="missing_model_probability")

    atr_pct = _atr_pct_from_state(account_state)
    if atr_pct is None:
        return _decision(
            enabled=True,
            action="none",
            reason="missing_atr_context",
            model_prob=model_prob,
        )

    predicted_slippage_pct = _predicted_slippage_pct(account_state)
    if predicted_slippage_pct is None:
        return _decision(
            enabled=True,
            action="none",
            reason="missing_predicted_slippage",
            model_prob=model_prob,
        )

    reward_mult = _env_float("SLIPPAGE_KELLY_PROFIT_ATR_MULT", 2.0)
    risk_mult = _env_float("SLIPPAGE_KELLY_STOP_ATR_MULT", 1.5)
    slippage_turns = _env_float("SLIPPAGE_KELLY_ROUND_TRIP_MULT", 2.0)
    max_friction = _env_float("SLIPPAGE_KELLY_MAX_FRICTION_RATIO", 0.20)
    max_alpha_friction = _env_float("SLIPPAGE_KELLY_MAX_ALPHA_FRICTION_RATIO", 0.35)
    fractional_mult = _env_float("SLIPPAGE_KELLY_FRACTION", 0.25)
    max_cap_pct = _env_float("SLIPPAGE_KELLY_MAX_CAP_PCT", requested_size_pct)
    lsi_score, lsi_bucket = _liquidity_stress_from_state(account_state)
    lsi_multiplier, lsi_reason = _liquidity_stress_multiplier(
        score=lsi_score,
        bucket=lsi_bucket,
        account_state=account_state,
    )

    raw_reward_pct = reward_mult * atr_pct
    raw_risk_pct = risk_mult * atr_pct
    round_trip_slip_pct = slippage_turns * predicted_slippage_pct
    adjusted_reward_pct = raw_reward_pct - round_trip_slip_pct
    adjusted_risk_pct = raw_risk_pct + round_trip_slip_pct

    if adjusted_reward_pct <= 0 or adjusted_risk_pct <= 0:
        return _decision(
            enabled=True,
            action="zero",
            reason="slippage_erases_reward",
            model_prob=model_prob,
            raw_reward_pct=raw_reward_pct,
            raw_risk_pct=raw_risk_pct,
            adjusted_reward_pct=adjusted_reward_pct,
            adjusted_risk_pct=adjusted_risk_pct,
            predicted_slippage_pct=predicted_slippage_pct,
            friction_ratio=1.0,
            liquidity_stress_score=lsi_score,
            liquidity_stress_bucket=lsi_bucket,
            liquidity_stress_size_multiplier=lsi_multiplier,
            pareto_frontier_selection=None,
            cap_pct=0.0,
        )

    friction_ratio = round_trip_slip_pct / raw_reward_pct if raw_reward_pct > 0 else 1.0
    adjusted_r = adjusted_reward_pct / adjusted_risk_pct
    timeout_minutes = _trade_timeout_minutes(account_state)
    alpha_friction_ratio = None
    if timeout_minutes is not None and timeout_minutes > 0:
        # Shorter horizons have less time to amortize round-trip friction.
        duration_adjustment = max(0.25, min(1.0, timeout_minutes / 15.0))
        alpha_friction_ratio = friction_ratio / duration_adjustment
    quote_multiplier, quote_reason = _quote_instability_multiplier(account_state)
    if alpha_friction_ratio is not None and alpha_friction_ratio > max_alpha_friction:
        return _decision(
            enabled=True,
            action="zero",
            reason=f"alpha_friction_ratio_exceeds_{max_alpha_friction:.2f}",
            model_prob=model_prob,
            raw_reward_pct=raw_reward_pct,
            raw_risk_pct=raw_risk_pct,
            adjusted_reward_pct=adjusted_reward_pct,
            adjusted_risk_pct=adjusted_risk_pct,
            adjusted_risk_reward_ratio=adjusted_r,
            predicted_slippage_pct=predicted_slippage_pct,
            friction_ratio=friction_ratio,
            alpha_friction_ratio=alpha_friction_ratio,
            quote_instability_multiplier=quote_multiplier,
            liquidity_stress_score=lsi_score,
            liquidity_stress_bucket=lsi_bucket,
            liquidity_stress_size_multiplier=lsi_multiplier,
            pareto_frontier_selection=None,
            cap_pct=0.0,
        )
    if friction_ratio > max_friction:
        return _decision(
            enabled=True,
            action="zero",
            reason=f"friction_ratio_exceeds_{max_friction:.2f}",
            model_prob=model_prob,
            raw_reward_pct=raw_reward_pct,
            raw_risk_pct=raw_risk_pct,
            adjusted_reward_pct=adjusted_reward_pct,
            adjusted_risk_pct=adjusted_risk_pct,
            adjusted_risk_reward_ratio=adjusted_r,
            predicted_slippage_pct=predicted_slippage_pct,
            friction_ratio=friction_ratio,
            alpha_friction_ratio=alpha_friction_ratio,
            quote_instability_multiplier=quote_multiplier,
            liquidity_stress_score=lsi_score,
            liquidity_stress_bucket=lsi_bucket,
            liquidity_stress_size_multiplier=lsi_multiplier,
            cap_pct=0.0,
        )

    # Kelly fraction for b:1 payoff odds is p - q / b.
    loss_prob = 1.0 - model_prob
    kelly_fraction = model_prob - (loss_prob / adjusted_r)
    kelly_fraction = max(0.0, kelly_fraction)
    fractional_kelly_pct = kelly_fraction * fractional_mult * 100.0
    cap_pct = max(0.0, min(requested_size_pct, max_cap_pct, fractional_kelly_pct))
    if lsi_multiplier < 1.0:
        cap_pct = max(0.0, cap_pct * lsi_multiplier)
    if quote_multiplier < 1.0:
        cap_pct = max(0.0, cap_pct * quote_multiplier)
    pareto_cap_pct, pareto = _pareto_frontier_selection(
        requested_size_pct=requested_size_pct,
        kelly_cap_pct=cap_pct,
        raw_risk_pct=raw_risk_pct,
        friction_ratio=friction_ratio,
        alpha_friction_ratio=alpha_friction_ratio,
        quote_multiplier=quote_multiplier,
        account_state=account_state,
    )
    if pareto.get("enabled"):
        cap_pct = min(cap_pct, pareto_cap_pct)
    action_out = "cap" if cap_pct < requested_size_pct else "none"
    if lsi_multiplier <= 0:
        action_out = "zero"
        reason = lsi_reason or "liquidity_stress_zero"
    elif lsi_multiplier < 1.0:
        reason = f"slippage_adjusted_kelly_cap:{lsi_reason or 'liquidity_stress'}"
    elif quote_multiplier < 1.0:
        reason = f"slippage_adjusted_kelly_cap:{quote_reason or 'quote_instability'}"
    elif pareto.get("enabled") and pareto.get("selected_objective") != "kelly_growth_cap_pct":
        reason = f"slippage_adjusted_kelly_cap:pareto_{pareto['selected_objective']}"
    else:
        reason = (
            "slippage_adjusted_kelly_cap"
            if action_out == "cap"
            else "slippage_adjusted_kelly_no_tighter_cap"
        )

    return _decision(
        enabled=True,
        action=action_out,
        reason=reason,
        model_prob=model_prob,
        raw_reward_pct=raw_reward_pct,
        raw_risk_pct=raw_risk_pct,
        adjusted_reward_pct=adjusted_reward_pct,
        adjusted_risk_pct=adjusted_risk_pct,
        adjusted_risk_reward_ratio=adjusted_r,
        predicted_slippage_pct=predicted_slippage_pct,
        friction_ratio=friction_ratio,
        alpha_friction_ratio=alpha_friction_ratio,
        quote_instability_multiplier=quote_multiplier,
        liquidity_stress_score=lsi_score,
        liquidity_stress_bucket=lsi_bucket,
        liquidity_stress_size_multiplier=lsi_multiplier,
        pareto_frontier_selection=pareto,
        kelly_fraction=kelly_fraction,
        fractional_kelly_pct=fractional_kelly_pct,
        cap_pct=cap_pct,
    )
