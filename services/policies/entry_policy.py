"""Entry policy decisions separated from signal orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from decision_thresholds import PREDICTION_GATE_THRESHOLDS
from services.observability import record_policy_comparison
from services.policy_controls import policy_family_enabled

logger = logging.getLogger(__name__)


def ml_prediction_compare_decision(prediction: dict | None) -> str | None:
    if not prediction:
        return None
    try:
        score = float(prediction.get("prediction_score"))
    except Exception:
        return "unknown"
    if score >= 65:
        return "support"
    if score >= 45:
        return "watch"
    return "avoid"


def ml_prediction_bucket(score) -> str:
    """Map a raw ML prediction_score to the reporting bucket name."""
    if score is None:
        return "unknown"
    s = float(score)
    if s >= 55:
        return "high_55_plus"
    if s >= 50:
        return "mid_50_55"
    if s >= 45:
        return "low_45_50"
    return "weak_below_45"


def _is_favorable_setup_label(label: str | None) -> bool:
    return label in {
        "confirmed_near_vwap_recovery",
        "near_vwap_weak_strength_followthrough",
        "oversold_weak_bounce_watch",
        "balanced_transition_state",
    }


def evaluate_signal_quality_gate(
    *,
    trend_direction,
    trend_strength,
    market_bias,
    setup_label,
    setup_policy_action,
    momentum_direction,
    momentum_pct,
    consecutive_buy_count,
    recent_favorable_setup=None,
    ml_prediction=None,
):
    """Evaluate the deterministic signal-quality gate."""
    if not policy_family_enabled("entry"):
        return {
            "gate_name": "deterministic_signal_quality_gate",
            "prediction_score": 0,
            "prediction_decision": "pass",
            "prediction_reason": "entry_policy_disabled",
            "deterministic_signal_quality_score": 0,
            "deterministic_signal_quality_decision": "pass",
            "deterministic_signal_quality_reason": "entry_policy_disabled",
            "ml_prediction_runtime_effect": "disabled",
            "policy_family_enabled": False,
        }

    score = 0
    reasons = []

    if trend_direction == "bullish":
        score += 2
        reasons.append("bullish_trend")
    elif trend_direction != "neutral":
        score -= 2
        reasons.append("non_bullish_trend")

    if trend_strength == "confirmed":
        score += 2
        reasons.append("confirmed_trend")
    elif trend_strength == "developing":
        score += 1
        reasons.append("developing_trend")
    else:
        score -= 1
        reasons.append("weak_trend")

    if market_bias == "buy":
        score += 2
        reasons.append("market_bias_buy")
    elif market_bias == "avoid":
        score -= 3
        reasons.append("market_bias_avoid")

    if setup_policy_action == "boost":
        score += 2
        reasons.append("setup_policy_boost")
    elif setup_policy_action == "block":
        score -= 4
        reasons.append("setup_policy_block")

    if setup_label in {
        "confirmed_near_vwap_recovery",
        "near_vwap_weak_strength_followthrough",
        "oversold_weak_bounce_watch",
    }:
        score += 1
        reasons.append("favorable_setup_label")
    elif setup_label in {
        "avoid_stretched_above_vwap_strength",
        "avoid_far_below_vwap_chase",
        "avoid_below_vwap_weak_drift",
    }:
        score -= 3
        reasons.append("avoid_setup_label")

    if recent_favorable_setup:
        recent_label = recent_favorable_setup.get("setup_label")
        recent_action = recent_favorable_setup.get("setup_policy_action")
        if recent_action == "boost":
            score += 1
            reasons.append("recent_boost_memory")
        if _is_favorable_setup_label(recent_label):
            score += 1
            reasons.append("recent_favorable_setup_memory")

    if momentum_direction == "rising":
        score += 1
        reasons.append("rising_momentum")
    elif momentum_direction == "falling":
        score -= 1
        reasons.append("falling_momentum")

    try:
        momentum_value = float(momentum_pct) if momentum_pct is not None else None
    except (TypeError, ValueError):
        momentum_value = None

    if momentum_value is not None:
        if momentum_value > 0.15:
            score += 1
            reasons.append("positive_momentum_pct")
        elif momentum_value < -0.15:
            score -= 1
            reasons.append("negative_momentum_pct")

    if consecutive_buy_count >= 3:
        score += 2
        reasons.append("three_plus_consecutive_buys")
    elif consecutive_buy_count == 2:
        score += 1
        reasons.append("two_consecutive_buys")
    elif consecutive_buy_count <= 0:
        score -= 1
        reasons.append("no_consecutive_buy_confirmation")

    if score >= PREDICTION_GATE_THRESHOLDS["pass_min_score"]:
        decision = "pass"
    elif score >= PREDICTION_GATE_THRESHOLDS["watch_min_score"]:
        decision = "watch"
    else:
        decision = "block"

    ml_compare_decision = ml_prediction_compare_decision(ml_prediction)
    ml_agrees = None
    if ml_compare_decision:
        deterministic_compare_decision = {
            "pass": "support",
            "watch": "watch",
            "block": "avoid",
        }.get(decision, "unknown")
        deterministic_positive = decision == "pass"
        ml_positive = ml_compare_decision == "support"
        deterministic_negative = decision == "block"
        ml_negative = ml_compare_decision == "avoid"
        ml_agrees = (
            (deterministic_positive and ml_positive)
            or (deterministic_negative and ml_negative)
            or (decision == "watch" and ml_compare_decision == "watch")
        )
        record_policy_comparison(
            "deterministic_signal_quality_vs_ml_prediction",
            deterministic_compare_decision,
            ml_compare_decision,
        )

    reason = ",".join(reasons)
    return {
        "gate_name": "deterministic_signal_quality_gate",
        "prediction_field_note": (
            "prediction_score/prediction_decision are deterministic gate fields; "
            "ml_prediction_* fields come from daily_symbol_predictions cache."
        ),
        "prediction_score": score,
        "prediction_decision": decision,
        "prediction_reason": reason,
        "deterministic_signal_quality_score": score,
        "deterministic_signal_quality_decision": decision,
        "deterministic_signal_quality_reason": reason,
        "ml_prediction_score": (ml_prediction or {}).get("prediction_score"),
        "ml_prediction_confidence": (ml_prediction or {}).get("confidence"),
        "ml_prediction_sample_size": (ml_prediction or {}).get("sample_size"),
        "ml_prediction_reason": (ml_prediction or {}).get("reason"),
        "ml_prediction_provider": (ml_prediction or {}).get("provider"),
        "ml_prediction_generated_at": (ml_prediction or {}).get("prediction_generated_at"),
        "ml_prediction_runtime_effect": "observe_only_compare",
        "ml_prediction_compare_decision": ml_compare_decision,
        "ml_prediction_agrees_with_gate": ml_agrees,
    }


def evaluate_prediction_gate(**kwargs):
    return evaluate_signal_quality_gate(**kwargs)


def evaluate_buy_opportunity(
    *,
    trend,
    setup_obs,
    bias_entry,
    macro_risk,
    session_momentum,
    momentum,
    prediction_gate=None,
    recent_favorable_setup=None,
    adaptive_buy_confirmation=None,
):
    """Observe-only BUY opportunity score."""
    score = 0
    reasons = []

    trend = trend or {}
    setup_obs = setup_obs or {}
    bias_entry = bias_entry or {}
    macro_risk = macro_risk or {}
    session_momentum = session_momentum or {}
    momentum = momentum or {}
    prediction_gate = prediction_gate or {}
    adaptive_buy_confirmation = adaptive_buy_confirmation or {}

    trend_direction = trend.get("direction")
    trend_strength = trend.get("strength")
    consecutive_count = int(trend.get("consecutive_count") or 0)

    if trend_direction == "bullish":
        score += 2
        reasons.append("bullish_trend:+2")
    elif trend_direction == "bearish":
        score -= 3
        reasons.append("bearish_trend:-3")
    else:
        score -= 1
        reasons.append("non_bullish_trend:-1")

    if trend_strength == "confirmed":
        score += 2
        reasons.append("confirmed_trend:+2")
    elif trend_strength == "developing":
        score += 1
        reasons.append("developing_trend:+1")
    elif trend_strength == "weak":
        score -= 1
        reasons.append("weak_trend:-1")

    if consecutive_count >= 4:
        score += 2
        reasons.append("4plus_buy_confirmations:+2")
    elif consecutive_count >= 2:
        score += 1
        reasons.append("2plus_buy_confirmations:+1")

    required_confirmations = int(
        adaptive_buy_confirmation.get("required_buy_confirmations") or 3
    )
    if required_confirmations == 2:
        score += 1
        reasons.append("adaptive_fast_lane:+1")
    elif required_confirmations >= 4:
        score -= 1
        reasons.append("adaptive_caution_required4:-1")

    session_label = session_momentum.get("trend_label")
    session_score = float(session_momentum.get("trend_score") or 0)
    session_15m = float(session_momentum.get("momentum_15m_pct") or 0)
    session_30m = float(session_momentum.get("momentum_30m_pct") or 0)
    session_60m = float(session_momentum.get("momentum_60m_pct") or 0)
    session_120m = float(session_momentum.get("momentum_120m_pct") or 0)
    session_vwap = float(session_momentum.get("distance_from_vwap_pct") or 0)
    trend_regime = session_momentum.get("trend_regime")
    pullback_score = int(session_momentum.get("pullback_with_trend_score") or 0)
    maturity_score = int(session_momentum.get("late_chase_maturity_score") or 0)
    reversal_score = int(session_momentum.get("reversal_attempt_score") or 0)

    if session_label == "strong_uptrend" or session_score >= 6:
        score += 3
        reasons.append("strong_session_momentum:+3")
    elif session_label == "developing_uptrend" or session_score >= 3:
        score += 2
        reasons.append("developing_session_momentum:+2")
    elif session_label in ("fading", "downtrend") or session_score <= -3:
        score -= 3
        reasons.append("negative_session_momentum:-3")

    if session_15m > 0 and session_30m > 0:
        score += 2
        reasons.append("15m_30m_positive:+2")
    elif session_15m < 0 and session_30m < 0:
        score -= 2
        reasons.append("15m_30m_negative:-2")

    if session_60m > 0 and session_120m > 0:
        score += 1
        reasons.append("60m_120m_positive_regime:+1")
    elif session_60m < 0 and session_120m < 0:
        score -= 1
        reasons.append("60m_120m_negative_regime:-1")

    if trend_regime == "pullback_with_uptrend" or pullback_score >= 3:
        score += 2
        reasons.append("pullback_with_uptrend:+2")
    elif trend_regime == "mature_uptrend" or maturity_score >= 3:
        score -= 2
        reasons.append("mature_uptrend_chase:-2")
    elif trend_regime == "reversal_attempt" or reversal_score >= 2:
        score += 1
        reasons.append("longer_reversal_attempt:+1")

    if session_vwap > 0.25:
        score += 1
        reasons.append("above_vwap:+1")
    elif session_vwap < -0.25:
        score -= 1
        reasons.append("below_vwap:-1")

    setup_label = setup_obs.get("setup_label")
    setup_action = setup_obs.get("setup_policy_action")

    if setup_action == "boost":
        score += 3
        reasons.append("setup_boost:+3")
    elif setup_action in ("allow", "neutral"):
        score += 1
        reasons.append("setup_allows:+1")
    elif setup_action == "block":
        score -= 4
        reasons.append("setup_block:-4")

    favorable_setups = {
        "confirmed_near_vwap_recovery",
        "near_vwap_weak_strength_followthrough",
        "oversold_weak_bounce_watch",
        "balanced_transition_state",
    }

    risky_setups = {
        "avoid_stretched_above_vwap_strength",
        "avoid_far_below_vwap_chase",
        "avoid_below_vwap_weak_drift",
        "below_vwap_neutral_drift_risk",
        "late_strength_near_vwap_risk",
        "above_vwap_strength_continuation",
    }

    if setup_label in favorable_setups:
        score += 2
        reasons.append(f"favorable_setup:{setup_label}:+2")
    elif setup_label in risky_setups:
        score -= 2
        reasons.append(f"risky_setup:{setup_label}:-2")

    if recent_favorable_setup:
        score += 1
        reasons.append("recent_favorable_setup:+1")

    bias = bias_entry.get("bias")
    risk_level = bias_entry.get("risk_level")
    entry_quality = bias_entry.get("entry_quality")

    if bias == "buy":
        score += 2
        reasons.append("market_bias_buy:+2")
    elif bias == "avoid":
        score -= 4
        reasons.append("market_bias_avoid:-4")

    if risk_level == "low":
        score += 1
        reasons.append("low_risk:+1")
    elif risk_level == "high":
        score -= 1
        reasons.append("high_risk:-1")
    elif risk_level == "very_high":
        score -= 3
        reasons.append("very_high_risk:-3")

    if entry_quality in (
        "excellent",
        "good_on_pullbacks",
        "good_if_holds_gap",
        "good_if_breadth_holds",
    ):
        score += 2
        reasons.append(f"good_entry_quality:{entry_quality}:+2")
    elif entry_quality in ("tactical_only", "conditional", "hedge_only"):
        score -= 1
        reasons.append(f"limited_entry_quality:{entry_quality}:-1")
    elif entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
        score -= 4
        reasons.append(f"poor_entry_quality:{entry_quality}:-4")

    macro_regime = macro_risk.get("macro_regime")
    risk_multiplier = float(macro_risk.get("risk_multiplier") or 1.0)

    if macro_regime in ("risk_on", "bullish"):
        score += 2
        reasons.append("macro_risk_on:+2")
    elif macro_regime in ("caution", "mixed", "neutral"):
        reasons.append(f"macro_{macro_regime}:0")
    elif macro_regime in ("defensive", "capital_preservation"):
        score -= 3
        reasons.append(f"macro_{macro_regime}:-3")

    if risk_multiplier < 1.0:
        score -= 1
        reasons.append("macro_risk_multiplier_below_1:-1")

    pred_score = prediction_gate.get("prediction_score")
    pred_decision = prediction_gate.get("prediction_decision")
    if pred_score is not None:
        try:
            pred_score = int(pred_score)
            if pred_score >= 8:
                score += 2
                reasons.append("prediction_score>=8:+2")
            elif pred_score >= 6:
                score += 1
                reasons.append("prediction_score>=6:+1")
            elif pred_decision == "block":
                score -= 3
                reasons.append("prediction_block:-3")
        except Exception:
            pass

    raw_momentum_direction = momentum.get("direction")
    if raw_momentum_direction == "rising":
        score += 1
        reasons.append("short_momentum_rising:+1")
    elif raw_momentum_direction == "falling":
        score -= 1
        reasons.append("short_momentum_falling:-1")

    if score >= 10:
        recommendation = "strong_buy_candidate"
    elif score >= 7:
        recommendation = "small_buy_candidate"
    elif score >= 4:
        recommendation = "watch"
    else:
        recommendation = "avoid"

    return {
        "buy_opportunity_score": score,
        "buy_opportunity_points_score": score,
        "score_scale": "points",
        "buy_opportunity_recommendation": recommendation,
        "buy_opportunity_reason": ",".join(reasons),
    }


def live_bias_override(symbol, bias_entry, trend, setup_obs, prediction_gate, momentum):
    """Convert pre-market bias into effective live intraday bias."""
    if not policy_family_enabled("entry"):
        return {
            "effective_bias": (bias_entry or {}).get("bias") or "neutral",
            "allow_buy": True,
            "confidence_adjustment": 0,
            "reason": "entry_policy_disabled",
        }

    bias_entry = bias_entry or {}
    trend = trend or {}
    setup_obs = setup_obs or {}
    prediction_gate = prediction_gate or {}
    momentum = momentum or {}

    bias = bias_entry.get("bias")
    avoid_type = (bias_entry.get("avoid_type") or "").lower()
    fundamental_score = bias_entry.get("fundamental_score")
    entry_quality = bias_entry.get("entry_quality")

    trend_direction = trend.get("direction")
    trend_strength = trend.get("strength")
    consecutive_count = int(trend.get("consecutive_count") or 0)
    last_signal = trend.get("last_signal")
    setup_action = setup_obs.get("setup_policy_action")
    setup_label = setup_obs.get("setup_label")
    prediction_score = int(prediction_gate.get("prediction_score") or 0)
    prediction_decision = prediction_gate.get("prediction_decision")
    momentum_direction = momentum.get("direction")

    if bias == "avoid" and avoid_type != "soft":
        return {
            "effective_bias": "avoid_hard",
            "allow_buy": False,
            "confidence_adjustment": -30,
            "reason": "hard pre-market avoid remains active",
        }

    if fundamental_score in ("bearish", "strong_bearish"):
        return {
            "effective_bias": "avoid_hard",
            "allow_buy": False,
            "confidence_adjustment": -30,
            "reason": f"fundamental_score={fundamental_score} remains hard block",
        }

    if entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
        return {
            "effective_bias": "avoid_hard",
            "allow_buy": False,
            "confidence_adjustment": -30,
            "reason": f"entry_quality={entry_quality} remains hard block",
        }

    live_positive = (
        trend_direction == "bullish"
        and last_signal == "buy"
        and consecutive_count >= 3
        and momentum_direction == "rising"
        and prediction_decision == "pass"
        and prediction_score >= 6
        and setup_action in ("boost", "allow", "neutral")
    )
    live_strong_positive = (
        live_positive
        and trend_strength in ("developing", "confirmed")
        and prediction_score >= 8
        and setup_action in ("boost", "allow")
    )
    live_negative = (
        trend_direction == "bearish"
        or momentum_direction == "falling"
        or prediction_decision == "block"
        or setup_action == "block"
    )

    if bias == "avoid" and avoid_type == "soft":
        if live_strong_positive:
            return {
                "effective_bias": "live_override_buy",
                "allow_buy": True,
                "confidence_adjustment": -5,
                "reason": (
                    "soft avoid overridden by live confirmation: "
                    f"trend={trend_direction}/{trend_strength}, count={consecutive_count}, "
                    f"setup={setup_label}, setup_action={setup_action}, "
                    f"prediction_score={prediction_score}, momentum={momentum_direction}"
                ),
            }
        return {
            "effective_bias": "avoid_soft",
            "allow_buy": False,
            "confidence_adjustment": -15,
            "reason": (
                "soft avoid still active; requires stronger live confirmation: "
                f"trend={trend_direction}/{trend_strength}, count={consecutive_count}, "
                f"setup_action={setup_action}, prediction_score={prediction_score}, "
                f"prediction_decision={prediction_decision}, momentum={momentum_direction}"
            ),
        }

    if bias == "buy" and live_negative:
        return {
            "effective_bias": "live_override_neutral",
            "allow_buy": False,
            "confidence_adjustment": -20,
            "reason": (
                "pre-market buy downgraded by live evidence: "
                f"trend={trend_direction}/{trend_strength}, setup_action={setup_action}, "
                f"prediction_decision={prediction_decision}, momentum={momentum_direction}"
            ),
        }

    if bias == "neutral" and live_strong_positive:
        return {
            "effective_bias": "live_override_buy",
            "allow_buy": True,
            "confidence_adjustment": 5,
            "reason": (
                "neutral pre-market bias upgraded by strong live evidence: "
                f"trend={trend_direction}/{trend_strength}, setup={setup_label}, "
                f"prediction_score={prediction_score}, momentum={momentum_direction}"
            ),
        }

    return {
        "effective_bias": bias or "neutral",
        "allow_buy": bias != "avoid",
        "confidence_adjustment": 0,
        "reason": "pre-market bias unchanged by live evidence",
    }


def required_buy_confirmations(
    symbol: str,
    account_state: dict[str, Any] | None,
    *,
    load_market_context: Callable[[], None],
    market_bias: dict[str, dict[str, Any]],
    get_macro_risk: Callable[[Path], dict[str, Any]],
    base_dir: Path,
    symbol_market_alignment: Callable[[str], dict[str, Any]],
    log: logging.Logger | None = None,
) -> dict[str, Any]:
    """Return adaptive BUY confirmation requirement."""
    if not policy_family_enabled("entry"):
        return {
            "required_buy_confirmations": 3,
            "current_rule_required_buy_confirmations": 3,
            "observe_only": True,
            "policy_family_enabled": False,
            "reason": "entry_policy_disabled",
        }

    log = log or logger
    account_state = account_state or {}
    try:
        symbol = symbol.upper()
        load_market_context()
        bias_entry = market_bias.get(symbol) or {}
        market_bias_value = bias_entry.get("bias")
        risk_level = bias_entry.get("risk_level")
        entry_quality = bias_entry.get("entry_quality")
        macro_risk = account_state.get("macro_risk") or get_macro_risk(base_dir)
        macro_regime = macro_risk.get("macro_regime")
        alignment = account_state.get("market_alignment") or symbol_market_alignment(symbol)
        aligned_for_buy = alignment.get("aligned_for_buy")

        required = 3
        reasons = ["base requirement is 3 BUY confirmations"]
        setup_obs = account_state.get("setup_observation") or {}
        setup_policy_action = setup_obs.get("setup_policy_action")
        alignment_reason = str(alignment.get("reason", "")).lower()
        alignment_hard_negative = (
            "benchmark avoid" in alignment_reason
            or "benchmark bearish" in alignment_reason
            or "symbol avoid" in alignment_reason
        )
        setup_allows_fast_lane = setup_policy_action in (
            None,
            "",
            "boost",
            "allow",
            "neutral",
            "not_applicable",
        )

        fast_lane_eligible = (
            macro_regime in ("risk_on", "bullish", "normal", "caution", "mixed", "neutral")
            and market_bias_value == "buy"
            and entry_quality in (
                "excellent",
                "good_on_pullbacks",
                "good_if_holds_gap",
                "good_if_breadth_holds",
            )
            and risk_level in ("low", "medium")
            and setup_allows_fast_lane
            and not alignment_hard_negative
        )

        if fast_lane_eligible:
            required = 2
            reasons.append(
                "reduced to 2: clean buy-bias setup with low/medium risk and no hard benchmark conflict"
            )

        if risk_level == "very_high":
            required = max(required, 4)
            reasons.append("raised to 4: very_high risk")
        if entry_quality in ("tactical_only", "conditional"):
            required = max(required, 3)
            reasons.append(f"minimum 3: entry_quality={entry_quality}")
        if entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
            required = max(required, 4)
            reasons.append(f"raised to 4: entry_quality={entry_quality}")
        if macro_regime in ("defensive", "capital_preservation"):
            required = max(required, 4)
            reasons.append(f"raised to 4: macro_regime={macro_regime}")

        if aligned_for_buy is False:
            if fast_lane_eligible:
                reasons.append("kept at 2: fast-lane setup allowed despite soft alignment caution")
            elif (
                risk_level in ("high", "very_high")
                or entry_quality in (
                    "tactical_only",
                    "conditional",
                    "do_not_chase",
                    "avoid_chasing",
                    "poor",
                )
                or macro_regime in ("defensive", "capital_preservation")
            ):
                required = max(required, 4)
                reasons.append("raised to 4: market alignment caution plus elevated symbol/setup risk")
            else:
                required = max(required, 3)
                reasons.append("kept at 3: market alignment caution without elevated symbol/setup risk")

        return {
            "required_buy_confirmations": required,
            "current_rule_required_buy_confirmations": 3,
            "macro_regime": macro_regime,
            "market_bias": market_bias_value,
            "risk_level": risk_level,
            "entry_quality": entry_quality,
            "aligned_for_buy": aligned_for_buy,
            "observe_only": True,
            "reason": "; ".join(reasons),
        }
    except Exception as exc:
        log.error(f"required_buy_confirmations failed for {symbol}: {exc}")
        return {
            "required_buy_confirmations": 3,
            "current_rule_required_buy_confirmations": 3,
            "observe_only": True,
            "reason": f"adaptive confirmation error: {exc}",
        }


def required_sell_confirmations(symbol, account_state=None):
    if not policy_family_enabled("entry"):
        return {
            "required_sell_confirmations": 2,
            "current_rule_required_sell_confirmations": 2,
            "observe_only": True,
            "policy_family_enabled": False,
            "reason": "entry_policy_disabled",
        }

    return {
        "required_sell_confirmations": 2,
        "current_rule_required_sell_confirmations": 2,
        "observe_only": False,
        "reason": "base requirement is 2 SELL confirmations",
    }


def evaluate_session_momentum_gate(session_momentum, prediction_gate, setup_obs, trend):
    """Return a BUY session-momentum gate decision."""
    if not policy_family_enabled("entry"):
        return {
            "would_block": False,
            "severity": "disabled",
            "reason": "entry_policy_disabled",
        }

    session_momentum = session_momentum or {}
    prediction_gate = prediction_gate or {}
    setup_obs = setup_obs or {}
    trend = trend or {}

    session_label = session_momentum.get("trend_label")
    session_score = int(session_momentum.get("trend_score") or 0)
    trend_regime = session_momentum.get("trend_regime")
    maturity_score = int(session_momentum.get("late_chase_maturity_score") or 0)
    pullback_score = int(session_momentum.get("pullback_with_trend_score") or 0)
    prediction_score = int(prediction_gate.get("prediction_score") or 0)
    setup_action = setup_obs.get("setup_policy_action")
    trend_direction = trend.get("direction")
    trend_strength = trend.get("strength")

    session_hard_negative = session_label == "downtrend" or session_score <= -5
    session_soft_negative = session_label == "fading" or session_score <= -2
    session_reversal = session_label == "reversal_attempt"
    mature_chase = trend_regime == "mature_uptrend" or maturity_score >= 4
    constructive_pullback = trend_regime == "pullback_with_uptrend" or pullback_score >= 3

    if mature_chase and setup_action != "boost" and not constructive_pullback:
        return {
            "would_block": False,
            "severity": "mature_chase_caution",
            "size_hint": "reduce",
            "reason": (
                f"session_regime={trend_regime} maturity_score={maturity_score} "
                f"setup_action={setup_action} prediction_score={prediction_score}"
            ),
        }

    if session_hard_negative and setup_action != "boost":
        return {
            "would_block": True,
            "severity": "hard_negative",
            "reason": (
                f"session_label={session_label} score={session_score} "
                f"setup_action={setup_action} prediction_score={prediction_score}"
            ),
        }

    if (
        session_soft_negative
        and prediction_score < 8
        and not (
            trend_direction == "bullish"
            and trend_strength == "confirmed"
            and setup_action == "boost"
        )
    ):
        return {
            "would_block": True,
            "severity": "soft_negative",
            "reason": (
                f"session_label={session_label} score={session_score} "
                f"prediction_score={prediction_score} trend={trend_direction}/{trend_strength} "
                f"setup_action={setup_action}"
            ),
        }

    if session_reversal:
        return {
            "would_block": False,
            "severity": "reversal_caution",
            "size_hint": "reduce",
            "reason": (
                f"session_label=reversal_attempt score={session_score} "
                f"prediction_score={prediction_score} trend={trend_direction}/{trend_strength} "
                f"setup_action={setup_action} - allow with caution sizing"
            ),
        }

    return {
        "would_block": False,
        "severity": "pass",
        "reason": (
            f"session_label={session_label} score={session_score} "
            f"prediction_score={prediction_score} trend={trend_direction}/{trend_strength} "
            f"setup_action={setup_action}"
        ),
    }
