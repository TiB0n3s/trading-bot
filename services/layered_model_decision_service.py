"""Layered model decision payload for regime, ensemble, meta-label, and sizing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

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

    strategy = _historical_strategy(symbol=symbol, action=action, account_state=account_state)
    historical_prob = _probability(strategy.get("master_confidence_score"))
    if historical_prob is not None:
        experts.append(
            {
                "expert": "historical_bar_ensemble",
                "probability": round(historical_prob, 6),
                "weight": 0.45,
                "status": strategy.get("status"),
                "recommendation": strategy.get("paper_recommendation"),
                "source": "trend_scan_triple_barrier_weighted_ensemble",
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
        experts.append(
            {
                "expert": "transformer_authority",
                "probability": round(transformer_prob, 6),
                "weight": 0.25,
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
        experts.append(
            {
                "expert": "supervised_prediction",
                "probability": round(prediction_prob, 6),
                "weight": 0.30,
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
) -> dict[str, Any]:
    config = _dict((ml_authority_config or {}).get("historical_bar_meta_label_authority"))
    outcome = evaluate_historical_bar_meta_label_authority(
        symbol=symbol,
        action=action,
        decision=decision,
        account_state=account_state,
        execution_mode=execution_mode,
        config=config,
    )
    threshold = _probability(config.get("min_approve_score") or 65.0) or 0.65
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
) -> dict[str, Any]:
    requested_size = _float(decision.get("position_size_pct")) or _float(
        account_state.get("position_size_pct")
    )
    if requested_size is None or requested_size <= 0:
        requested_size = 1.0
    meta_size = _float(_dict(meta_label.get("authority")).get("position_size_pct"))
    base_size = meta_size if meta_size is not None and meta_size >= 0 else requested_size
    regime_modifier = _float(regime.get("size_modifier")) or 1.0
    regime_adjusted = max(0.0, base_size * regime_modifier)

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
    )
    sizing = _sizing_layer(
        action=action_l,
        decision=decision,
        account_state=account_state,
        ensemble_probability=ensemble_probability,
        meta_label=meta_label,
        regime=regime,
    )

    reasons = [
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
