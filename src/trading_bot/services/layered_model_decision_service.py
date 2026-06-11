"""Layered model decision payload for regime, ensemble, meta-label, and sizing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from services.alternative_data_gate_service import evaluate_alternative_data_gate
from services.counterfactual_learning_service import (
    evaluate_counterfactual_veto_relaxation,
)
from services.historical_bar_meta_label_authority_service import (
    evaluate_historical_bar_meta_label_authority,
)
from services.historical_bar_paper_strategy_service import build_historical_bar_paper_strategy
from services.slippage_kelly_sizing_service import calculate_slippage_adjusted_kelly_cap
from services.transformer_authority_model_service import evaluate_transformer_authority

LAYERED_MODEL_DECISION_VERSION = "layered_model_decision_v1"
LAYERED_MODEL_DECISION_RUNTIME_EFFECT = "paper_model_decision_context_no_order_submission"


@dataclass(frozen=True)
class LayeredModelDecision:
    version: str
    runtime_effect: str
    symbol: str
    action: str
    final_instruction: str
    final_size_pct: float
    level_0_alternative_gates: dict[str, Any]
    level_0_regime: dict[str, Any]
    level_1_expert_ensemble: dict[str, Any]
    level_2_meta_label: dict[str, Any]
    level_3_sizing: dict[str, Any]
    reasons: list[str]
    guardrails: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
    except Exception:
        return None
    return result if result == result else None


def _probability(value: Any) -> float | None:
    parsed = _float(value)
    if parsed is None:
        return None
    if parsed > 1.0:
        parsed = parsed / 100.0
    if 0.0 <= parsed <= 1.0:
        return parsed
    return None


def _confidence_bucket(probability: float | None) -> str:
    if probability is None:
        return "unscored"
    if probability >= 0.75:
        return "high"
    if probability >= 0.60:
        return "medium"
    if probability >= 0.50:
        return "low"
    return "veto"


def _microstructure_alpha_features(account_state: dict[str, Any]) -> dict[str, Any]:
    features = _dict(account_state.get("bar_pattern_features"))
    context = _dict(account_state.get("microstructure_features"))
    merged = {**features, **context}
    variance_ratio = _float(
        merged.get("variance_ratio_30m")
        or merged.get("rolling_variance_ratio_30m")
        or account_state.get("variance_ratio_30m")
    )
    vwap_distance = _float(
        merged.get("distance_from_vwap_pct")
        or merged.get("vwap_distance_pct")
        or account_state.get("session_distance_from_vwap_pct")
    )
    vwap_std = _float(
        merged.get("vwap_rolling_std_pct")
        or merged.get("vwap_std_30m_pct")
        or merged.get("rolling_vwap_std_pct")
    )
    vwap_band_zscore = _float(merged.get("vwap_band_zscore"))
    if vwap_band_zscore is None and vwap_distance is not None and vwap_std and vwap_std > 0:
        vwap_band_zscore = vwap_distance / vwap_std
    trend_weight_modifier = 1.0
    triple_barrier_weight_modifier = 1.0
    regime_hint = "unknown"
    if variance_ratio is not None:
        if variance_ratio >= 1.10:
            trend_weight_modifier = 1.20
            triple_barrier_weight_modifier = 0.90
            regime_hint = "trend_persistence"
        elif variance_ratio <= 0.90:
            trend_weight_modifier = 0.90
            triple_barrier_weight_modifier = 1.15
            regime_hint = "mean_reversion_random_walk"
        else:
            regime_hint = "near_random_walk"
    exhaustion_risk = vwap_band_zscore is not None and abs(vwap_band_zscore) >= 2.0
    return {
        "variance_ratio_30m": round(variance_ratio, 6) if variance_ratio is not None else None,
        "vwap_band_zscore": round(vwap_band_zscore, 6) if vwap_band_zscore is not None else None,
        "trend_weight_modifier": round(trend_weight_modifier, 4),
        "triple_barrier_weight_modifier": round(triple_barrier_weight_modifier, 4),
        "regime_hint": regime_hint,
        "vwap_exhaustion_risk": exhaustion_risk,
    }


def _horizon_probability(payload: dict[str, Any], horizon: str) -> float | None:
    horizon_payload = _dict(payload.get(horizon))
    return (
        _probability(horizon_payload.get("probability"))
        or _probability(horizon_payload.get("p_favorable"))
        or _probability(payload.get(f"p_favorable_{horizon}"))
        or _probability(payload.get(f"probability_{horizon}"))
    )


def _horizon_return(payload: dict[str, Any], horizon: str) -> float | None:
    horizon_payload = _dict(payload.get(horizon))
    return (
        _float(horizon_payload.get("expected_return_pct"))
        or _float(horizon_payload.get("forecast_return_pct"))
        or _float(payload.get(f"expected_return_pct_{horizon}"))
        or _float(payload.get(f"forecast_return_pct_{horizon}"))
    )


def _multi_horizon_path_features(account_state: dict[str, Any]) -> dict[str, Any]:
    """Normalize optional TFT/Mamba-style horizon forecasts for Layer 2."""
    payload = (
        _dict(account_state.get("multi_horizon_path"))
        or _dict(account_state.get("multi_horizon_forecast"))
        or _dict(account_state.get("tft_multi_horizon_forecast"))
    )
    if not payload:
        return {
            "status": "missing_context_neutral",
            "provider": "not_available",
            "trend_velocity": None,
            "medium_term_decay_risk": False,
            "reason": "no multi-horizon path forecast supplied",
        }

    p5 = _horizon_probability(payload, "t5")
    p15 = _horizon_probability(payload, "t15")
    p60 = _horizon_probability(payload, "t60")
    r5 = _horizon_return(payload, "t5")
    r15 = _horizon_return(payload, "t15")
    r60 = _horizon_return(payload, "t60")

    trend_velocity = None
    if p5 is not None and p60 is not None:
        trend_velocity = p60 - p5
    elif r5 is not None and r60 is not None:
        trend_velocity = r60 - r5

    short_positive = bool(
        (p5 is not None and p5 >= 0.60)
        or (r5 is not None and r5 > 0)
        or (p15 is not None and p15 >= 0.60)
        or (r15 is not None and r15 > 0)
    )
    medium_decays = bool(
        short_positive
        and (
            (p60 is not None and p60 <= 0.45)
            or (r60 is not None and r60 < 0)
            or (trend_velocity is not None and trend_velocity <= -0.20)
        )
    )
    return {
        "status": "scored",
        "provider": payload.get("provider") or "account_state_multi_horizon",
        "p_favorable_t5": round(p5, 6) if p5 is not None else None,
        "p_favorable_t15": round(p15, 6) if p15 is not None else None,
        "p_favorable_t60": round(p60, 6) if p60 is not None else None,
        "expected_return_pct_t5": round(r5, 6) if r5 is not None else None,
        "expected_return_pct_t15": round(r15, 6) if r15 is not None else None,
        "expected_return_pct_t60": round(r60, 6) if r60 is not None else None,
        "trend_velocity": round(trend_velocity, 6) if trend_velocity is not None else None,
        "medium_term_decay_risk": medium_decays,
        "reason": (
            "short horizon positive while medium horizon decays"
            if medium_decays
            else "multi-horizon path is not decaying against the trade"
        ),
    }


def _regime_layer(account_state: dict[str, Any], action: str) -> dict[str, Any]:
    routing = _dict(account_state.get("regime_routing_decision"))
    if not routing:
        regime_payload = _dict(account_state.get("regime_observation"))
        routing = _dict(regime_payload.get("regime_routing_decision"))
    if not routing:
        routing = _dict(account_state.get("regime_routing"))

    size_modifier = _float(routing.get("size_modifier"))
    if size_modifier is None:
        size_modifier = 1.0
    allow_new_longs = routing.get("allow_new_longs")
    allow_new_longs = True if allow_new_longs is None else bool(allow_new_longs)
    action_l = str(action or "").lower()
    blocks = bool(action_l == "buy" and (not allow_new_longs or size_modifier <= 0))
    return {
        "level": 0,
        "name": "regime_filter",
        "status": "active" if routing else "missing_context_neutral",
        "regime_id": routing.get("regime_id"),
        "regime_label": routing.get("regime_label") or "unknown",
        "active_model_slot": routing.get("active_model_slot") or "default_expert_ensemble",
        "sub_model_strategy": routing.get("sub_model_strategy") or "default",
        "allow_new_longs": allow_new_longs,
        "size_modifier": round(size_modifier, 4),
        "decision": "veto" if blocks else "pass",
        "reason": (
            "regime blocks new long exposure" if blocks else "regime permits Layer-1 scoring"
        ),
    }


def _regime_model_weight_multipliers(account_state: dict[str, Any]) -> dict[str, Any]:
    routing = (
        _dict(account_state.get("regime_routing_decision"))
        or _dict(account_state.get("regime_routing"))
        or _dict(_dict(account_state.get("regime_observation")).get("regime_routing_decision"))
    )
    raw = (
        _dict(account_state.get("regime_model_weight_multipliers"))
        or _dict(account_state.get("strategy_memory_regime_weights"))
        or _dict(routing.get("model_weight_multipliers"))
        or _dict(routing.get("model_weights"))
    )
    multipliers: dict[str, float] = {}
    for key, value in raw.items():
        parsed = _float(value)
        if parsed is None:
            continue
        multipliers[str(key)] = max(0.0, min(3.0, parsed))
    return {
        "source": "account_state" if multipliers else "default",
        "regime_id": routing.get("regime_id"),
        "regime_label": routing.get("regime_label"),
        "active_model_slot": routing.get("active_model_slot"),
        "multipliers": multipliers,
    }


def _apply_regime_weight(
    base_weight: float,
    *,
    expert: str,
    regime_weights: dict[str, Any],
) -> tuple[float, float]:
    multipliers = _dict(regime_weights.get("multipliers"))
    multiplier = _float(multipliers.get(expert))
    if multiplier is None:
        multiplier = 1.0
    return base_weight * multiplier, multiplier


def _historical_strategy(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any],
) -> dict[str, Any]:
    strategy = _dict(account_state.get("historical_bar_paper_strategy"))
    if not strategy:
        strategy = build_historical_bar_paper_strategy(
            symbol=symbol,
            action=action,
            account_state=account_state,
        ).to_dict()
    return strategy


def _expert_components(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any],
    env: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    experts: list[dict[str, Any]] = []
    micro_alpha = _microstructure_alpha_features(account_state)
    multi_horizon = _multi_horizon_path_features(account_state)
    regime_weights = _regime_model_weight_multipliers(account_state)

    strategy = _historical_strategy(symbol=symbol, action=action, account_state=account_state)
    historical_prob = _probability(strategy.get("master_confidence_score"))
    if historical_prob is not None:
        model_weights = (
            strategy.get("model_weights") if isinstance(strategy.get("model_weights"), list) else []
        )
        trend_weight = 0.45
        if any(str(row.get("label_target")) == "trend_scan_label" for row in model_weights):
            trend_weight *= float(micro_alpha["trend_weight_modifier"])
        if any(str(row.get("label_target")) == "triple_barrier_label" for row in model_weights):
            trend_weight *= float(micro_alpha["triple_barrier_weight_modifier"])
        trend_weight, regime_multiplier = _apply_regime_weight(
            trend_weight,
            expert="historical_bar_ensemble",
            regime_weights=regime_weights,
        )
        experts.append(
            {
                "expert": "historical_bar_ensemble",
                "probability": round(historical_prob, 6),
                "weight": round(trend_weight, 6),
                "regime_weight_multiplier": round(regime_multiplier, 6),
                "status": strategy.get("status"),
                "recommendation": strategy.get("paper_recommendation"),
                "source": "trend_scan_triple_barrier_weighted_ensemble",
                "microstructure_alpha_features": micro_alpha,
            }
        )

    transformer = _dict(account_state.get("transformer_authority"))
    if not transformer:
        transformer = evaluate_transformer_authority(
            symbol=symbol,
            action=action,
            account_state=account_state,
            env=env,
        )
    transformer_prob = _probability(transformer.get("probability"))
    if transformer_prob is not None:
        weight, regime_multiplier = _apply_regime_weight(
            0.25,
            expert="transformer_authority",
            regime_weights=regime_weights,
        )
        experts.append(
            {
                "expert": "transformer_authority",
                "probability": round(transformer_prob, 6),
                "weight": round(weight, 6),
                "regime_weight_multiplier": round(regime_multiplier, 6),
                "status": transformer.get("status") or transformer.get("decision"),
                "recommendation": transformer.get("decision"),
                "source": "torch_transformer_authority",
            }
        )

    prediction_gate = _dict(account_state.get("prediction_gate"))
    prediction_prob = _probability(
        prediction_gate.get("ml_prediction_score")
        or prediction_gate.get("prediction_score")
        or account_state.get("prediction_score")
    )
    if prediction_prob is not None:
        weight, regime_multiplier = _apply_regime_weight(
            0.30,
            expert="supervised_prediction",
            regime_weights=regime_weights,
        )
        experts.append(
            {
                "expert": "supervised_prediction",
                "probability": round(prediction_prob, 6),
                "weight": round(weight, 6),
                "regime_weight_multiplier": round(regime_multiplier, 6),
                "status": prediction_gate.get("prediction_decision")
                or prediction_gate.get("deterministic_signal_quality_decision"),
                "recommendation": prediction_gate.get("ml_prediction_compare_decision"),
                "source": "supervised_prediction_gate",
            }
        )

    if not experts:
        return experts, {
            "level": 1,
            "name": "expert_ensemble",
            "status": "unscored",
            "ensemble_probability": None,
            "confidence_bucket": "unscored",
            "disagreement": None,
            "experts": [],
            "reason": "no expert probabilities available",
        }

    weight_total = sum(float(row["weight"]) for row in experts)
    ensemble = sum(float(row["probability"]) * float(row["weight"]) for row in experts)
    ensemble = ensemble / weight_total if weight_total > 0 else 0.0
    probabilities = [float(row["probability"]) for row in experts]
    disagreement = max(probabilities) - min(probabilities) if len(probabilities) > 1 else 0.0
    return experts, {
        "level": 1,
        "name": "expert_ensemble",
        "status": "scored",
        "ensemble_probability": round(ensemble, 6),
        "confidence_bucket": _confidence_bucket(ensemble),
        "disagreement": round(disagreement, 6),
        "experts": experts,
        "microstructure_alpha_features": micro_alpha,
        "multi_horizon_path": multi_horizon,
        "regime_model_weight_multipliers": regime_weights,
        "reason": "weighted expert ensemble scored candidate",
    }


def _meta_label_layer(
    *,
    symbol: str,
    action: str,
    decision: dict[str, Any],
    account_state: dict[str, Any],
    execution_mode: str,
    ml_authority_config: dict[str, Any] | None,
    ensemble_probability: float | None,
    level_1_ensemble: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = _dict((ml_authority_config or {}).get("historical_bar_meta_label_authority"))
    missed = _dict(account_state.get("missed_opportunity_relaxation"))
    relaxation = _float(
        missed.get("threshold_relaxation_pct")
        or missed.get("master_confidence_threshold_relaxation_pct")
        or account_state.get("missed_opportunity_threshold_relaxation_pct")
    )
    counterfactual_config = _dict((ml_authority_config or {}).get("counterfactual_veto_relaxation"))
    counterfactual_enabled = counterfactual_config.get("enabled")
    counterfactual_enabled = (
        True if counterfactual_enabled is None else bool(counterfactual_enabled)
    )
    counterfactual = evaluate_counterfactual_veto_relaxation(
        account_state=account_state,
        artifact_path=counterfactual_config.get("artifact_path")
        or account_state.get("veto_relaxation_model_path"),
        drift_artifact_path=counterfactual_config.get("drift_artifact_path")
        or account_state.get("veto_relaxation_drift_path"),
        enabled=counterfactual_enabled and str(action or "").lower() == "buy",
    )
    counterfactual_relaxation = _float(counterfactual.get("threshold_relaxation_pct"))
    if counterfactual_relaxation is not None and counterfactual_relaxation > 0:
        relaxation = max(_float(relaxation) or 0.0, counterfactual_relaxation)
    if relaxation is not None and relaxation > 0:
        config = dict(config)
        current_approve = _float(config.get("min_approve_score") or 65.0) or 65.0
        current_veto = _float(config.get("min_veto_score") or 65.0) or 65.0
        config["min_approve_score"] = max(0.0, current_approve - relaxation)
        config["min_veto_score"] = max(0.0, current_veto - relaxation)
    outcome = evaluate_historical_bar_meta_label_authority(
        symbol=symbol,
        action=action,
        decision=decision,
        account_state=account_state,
        execution_mode=execution_mode,
        config=config,
    )
    threshold = _probability(config.get("min_approve_score") or 65.0) or 0.65
    multi_horizon = _dict(_dict(level_1_ensemble).get("multi_horizon_path"))
    if (
        str(action or "").lower() == "buy"
        and multi_horizon.get("medium_term_decay_risk")
        and ensemble_probability is not None
        and ensemble_probability < max(0.75, threshold + 0.05)
    ):
        return {
            "level": 2,
            "name": "meta_labeler",
            "status": "active",
            "instruction": "veto",
            "effect": "multi_horizon_decay_veto",
            "success_probability": round(ensemble_probability, 6),
            "threshold": round(threshold, 4),
            "missed_opportunity_relaxation_pct": round(relaxation, 4)
            if relaxation is not None
            else None,
            "counterfactual_veto_relaxation": counterfactual,
            "multi_horizon_path": multi_horizon,
            "authority": outcome,
            "reason": "Level 1 multi-horizon path shows medium-term decay against buy candidate",
        }
    if outcome.get("allowed"):
        effect = str(outcome.get("effect") or "none")
        instruction = "veto" if effect == "veto" else "pass"
        return {
            "level": 2,
            "name": "meta_labeler",
            "status": "active",
            "instruction": instruction,
            "effect": effect,
            "success_probability": outcome.get("master_confidence_score"),
            "threshold": round(threshold, 4),
            "missed_opportunity_relaxation_pct": round(relaxation, 4)
            if relaxation is not None
            else None,
            "counterfactual_veto_relaxation": counterfactual,
            "multi_horizon_path": multi_horizon,
            "authority": outcome,
            "reason": outcome.get("reason"),
        }
    if ensemble_probability is not None and ensemble_probability < threshold:
        return {
            "level": 2,
            "name": "meta_labeler",
            "status": "active",
            "instruction": "veto",
            "effect": "ensemble_probability_veto",
            "success_probability": round(ensemble_probability, 6),
            "threshold": round(threshold, 4),
            "missed_opportunity_relaxation_pct": round(relaxation, 4)
            if relaxation is not None
            else None,
            "counterfactual_veto_relaxation": counterfactual,
            "multi_horizon_path": multi_horizon,
            "authority": outcome,
            "reason": (
                f"ensemble probability {ensemble_probability:.3f} below "
                f"meta-label threshold {threshold:.3f}"
            ),
        }
    return {
        "level": 2,
        "name": "meta_labeler",
        "status": "passive",
        "instruction": "pass",
        "effect": "none",
        "success_probability": round(ensemble_probability, 6)
        if ensemble_probability is not None
        else None,
        "threshold": round(threshold, 4),
        "missed_opportunity_relaxation_pct": round(relaxation, 4)
        if relaxation is not None
        else None,
        "counterfactual_veto_relaxation": counterfactual,
        "multi_horizon_path": multi_horizon,
        "authority": outcome,
        "reason": outcome.get("reason") or "meta-label clear",
    }


def _sizing_layer(
    *,
    action: str,
    decision: dict[str, Any],
    account_state: dict[str, Any],
    ensemble_probability: float | None,
    meta_label: dict[str, Any],
    regime: dict[str, Any],
    alternative_gate: dict[str, Any],
) -> dict[str, Any]:
    requested_size = _float(decision.get("position_size_pct")) or _float(
        account_state.get("position_size_pct")
    )
    if requested_size is None or requested_size <= 0:
        requested_size = 1.0
    meta_size = _float(_dict(meta_label.get("authority")).get("position_size_pct"))
    base_size = meta_size if meta_size is not None and meta_size >= 0 else requested_size
    regime_modifier = _float(regime.get("size_modifier")) or 1.0
    alternative_modifier = _float(alternative_gate.get("size_modifier")) or 1.0
    regime_adjusted = max(0.0, base_size * regime_modifier * alternative_modifier)

    sizing_state = dict(account_state)
    if ensemble_probability is not None:
        utility = dict(_dict(sizing_state.get("decision_utility")))
        utility["prob_favorable_move"] = ensemble_probability
        sizing_state["decision_utility"] = utility
    kelly = calculate_slippage_adjusted_kelly_cap(
        account_state=sizing_state,
        action=action,
        requested_size_pct=regime_adjusted,
    )
    final_size = regime_adjusted
    if kelly.cap_pct is not None:
        final_size = min(final_size, kelly.cap_pct)
    if kelly.action == "zero":
        final_size = 0.0
    return {
        "level": 3,
        "name": "sizing_and_execution_allocation",
        "requested_size_pct": round(requested_size, 4),
        "meta_label_size_pct": round(meta_size, 4) if meta_size is not None else None,
        "regime_size_modifier": round(regime_modifier, 4),
        "alternative_data_size_modifier": round(alternative_modifier, 4),
        "regime_adjusted_size_pct": round(regime_adjusted, 4),
        "kelly": kelly.to_dict(),
        "final_size_pct": round(final_size, 4),
        "reason": kelly.reason,
    }


def build_layered_model_decision(
    *,
    symbol: str,
    action: str,
    decision: dict[str, Any] | None = None,
    account_state: dict[str, Any] | None = None,
    execution_mode: str = "paper",
    ml_authority_config: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> LayeredModelDecision:
    """Build the Level 0-3 model decision stack for audit and paper authority."""
    decision = _dict(decision)
    account_state = _dict(account_state)
    symbol_u = str(symbol or account_state.get("symbol") or "").upper()
    action_l = str(action or account_state.get("action") or "buy").lower()

    regime = _regime_layer(account_state, action_l)
    alternative_gate = evaluate_alternative_data_gate(
        account_state=account_state,
        action=action_l,
    ).to_dict()
    _experts, ensemble = _expert_components(
        symbol=symbol_u,
        action=action_l,
        account_state=account_state,
        env=env,
    )
    ensemble_probability = _float(ensemble.get("ensemble_probability"))
    meta_label = _meta_label_layer(
        symbol=symbol_u,
        action=action_l,
        decision=decision,
        account_state=account_state,
        execution_mode=execution_mode,
        ml_authority_config=ml_authority_config,
        ensemble_probability=ensemble_probability,
        level_1_ensemble=ensemble,
    )
    sizing = _sizing_layer(
        action=action_l,
        decision=decision,
        account_state=account_state,
        ensemble_probability=ensemble_probability,
        meta_label=meta_label,
        regime=regime,
        alternative_gate=alternative_gate,
    )

    reasons = [
        "; ".join(str(reason) for reason in (alternative_gate.get("reasons") or [])[:3]),
        str(regime.get("reason")),
        str(ensemble.get("reason")),
        str(meta_label.get("reason")),
    ]
    final_instruction = "pass"
    final_size = float(sizing.get("final_size_pct") or 0.0)
    if regime.get("decision") == "veto":
        final_instruction = "veto"
        final_size = 0.0
        reasons.append("Level 0 regime veto")
    elif alternative_gate.get("decision") == "veto":
        final_instruction = "veto"
        final_size = 0.0
        reasons.append("Level 0 alternative-data veto")
    elif meta_label.get("instruction") == "veto":
        final_instruction = "veto"
        final_size = 0.0
        reasons.append("Level 2 meta-label veto")
    elif final_size <= 0 and action_l == "buy":
        final_instruction = "veto"
        reasons.append("Level 3 sizing reduced buy to zero")
    elif meta_label.get("effect") in {"paper_approval", "size_increase"}:
        final_instruction = str(meta_label.get("effect"))
    elif ensemble_probability is not None:
        final_instruction = "pass" if ensemble_probability >= 0.60 else "watch"

    return LayeredModelDecision(
        version=LAYERED_MODEL_DECISION_VERSION,
        runtime_effect=LAYERED_MODEL_DECISION_RUNTIME_EFFECT,
        symbol=symbol_u,
        action=action_l,
        final_instruction=final_instruction,
        final_size_pct=round(final_size, 4),
        level_0_alternative_gates=alternative_gate,
        level_0_regime=regime,
        level_1_expert_ensemble=ensemble,
        level_2_meta_label=meta_label,
        level_3_sizing=sizing,
        reasons=[reason for reason in reasons if reason and reason != "None"][:12],
        guardrails={
            "can_submit_orders": False,
            "paper_or_dry_run_authority_only": True,
            "hard_risk_gates_remain_external": True,
            "slippage_kelly_can_zero_size": True,
            "meta_label_can_veto": True,
        },
    )
