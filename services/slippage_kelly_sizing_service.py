"""Slippage-adjusted fractional Kelly sizing.

This module is a final sizing guard only. It can cap or zero a BUY size when
execution friction erodes expected edge; it cannot approve, loosen, or submit
orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import os
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
            round(adjusted_risk_reward_ratio, 4)
            if adjusted_risk_reward_ratio is not None
            else None
        ),
        predicted_slippage_pct=(
            round(predicted_slippage_pct, 4) if predicted_slippage_pct is not None else None
        ),
        friction_ratio=round(friction_ratio, 4) if friction_ratio is not None else None,
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
    enabled = (
        policy_family_enabled("sizing")
        and _env_bool("SLIPPAGE_KELLY_SIZING_ENABLED", True)
    )
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
    fractional_mult = _env_float("SLIPPAGE_KELLY_FRACTION", 0.25)
    max_cap_pct = _env_float("SLIPPAGE_KELLY_MAX_CAP_PCT", requested_size_pct)

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
            cap_pct=0.0,
        )

    friction_ratio = round_trip_slip_pct / raw_reward_pct if raw_reward_pct > 0 else 1.0
    adjusted_r = adjusted_reward_pct / adjusted_risk_pct
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
            cap_pct=0.0,
        )

    # Kelly fraction for b:1 payoff odds is p - q / b.
    loss_prob = 1.0 - model_prob
    kelly_fraction = model_prob - (loss_prob / adjusted_r)
    kelly_fraction = max(0.0, kelly_fraction)
    fractional_kelly_pct = kelly_fraction * fractional_mult * 100.0
    cap_pct = max(0.0, min(requested_size_pct, max_cap_pct, fractional_kelly_pct))
    action_out = "cap" if cap_pct < requested_size_pct else "none"
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
        kelly_fraction=kelly_fraction,
        fractional_kelly_pct=fractional_kelly_pct,
        cap_pct=cap_pct,
    )
