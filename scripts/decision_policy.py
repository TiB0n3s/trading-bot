#!/usr/bin/env python3
"""
Decision policy engine.

Purpose:
- Convert intelligence_context + strategy_memory into one deterministic policy.
- Runs before Claude.
- Never loosens hard risk rules.
- Can only block poor BUY setups or tell Claude to size down when the app's
  explicit decision-policy authority env settings allow it.
- Never increases size, submits orders, or overrides hard gates.
- SELL signals pass through.
"""

from __future__ import annotations

from services.confidence_calibration_service import build_calibrated_confidence
from services.decision_utility_service import estimate_decision_utility
from services.execution_quality_service import estimate_execution_quality
from services.market_regime_service import classify_market_regime
from services.portfolio_decision_service import evaluate_portfolio_decision
from services.rollout_contract_service import telemetry_only_rollout_contract
from services.strategy_memory_distribution_health_service import (
    evaluate_strategy_memory_distribution_health,
)
from services.transformer_authority_model_service import evaluate_transformer_authority
from strategy_constants import DAILY_LOSS_LIMIT_PCT
from strategy_memory import contextual_memory_for_signal

_HARD_GATE_CONTEXT_CHECKS = [
    # (account_state key path, condition_fn, block_reason)
    # Each check looks at account_state data that hard gates in app.py already enforce.
    # These checks make the policy self-contained for replay and audit; they do not
    # create new live authority. App hard gates are authoritative and should already
    # have run before this policy is evaluated.
    (
        lambda s: s.get("daily_pnl_pct"),
        lambda v: v is not None and v < DAILY_LOSS_LIMIT_PCT,
        "circuit_breaker: daily_pnl_pct below loss limit",
    ),
    (
        lambda s: (s.get("macro_risk") or {}).get("block_new_buys"),
        lambda v: bool(v),
        "macro_risk: block_new_buys is set",
    ),
    (
        lambda s: (s.get("account") or {}).get("circuit_breaker_active_for_buys"),
        lambda v: bool(v),
        "circuit_breaker: active per account state",
    ),
]


def _hard_gate_block(account_state):
    for extract, condition, reason in _HARD_GATE_CONTEXT_CHECKS:
        try:
            value = extract(account_state)
            if condition(value):
                return reason
        except Exception:
            pass
    return None


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _normalize_score(value):
    """Pass through a 0-100 score. opportunity_score.py already clamps to 0-100."""
    return _to_float(value)


def _worst_recommendation(recs):
    priority = {
        "avoid": 4,
        "caution": 3,
        "neutral": 2,
        "observe": 1,
        "favor": 0,
        None: 0,
    }
    if not recs:
        return None
    return max(recs, key=lambda r: priority.get(r, 0))


def _shadow_divergence_gate(account_state):
    health = account_state.get("shadow_prediction_health") or account_state.get(
        "shadow_model_health"
    )
    if not isinstance(health, dict):
        return {"decision": "pass", "reason": "shadow health unavailable"}
    status = str(health.get("status") or "").lower()
    rate = _to_float(health.get("divergence_rate"))
    max_rate = _to_float((health.get("thresholds") or {}).get("max_divergence_rate"))
    if max_rate is None:
        max_rate = 0.35
    if status == "divergence_alert" or (rate is not None and rate > max_rate):
        return {
            "decision": "block",
            "reason": (
                "shadow/live model divergence alert: "
                f"rate={rate} threshold={max_rate} rows={health.get('comparable_rows')}"
            ),
            "evidence": health,
        }
    return {"decision": "pass", "reason": "shadow/live model agreement within tolerance"}


def _quant_suite_gate(account_state):
    suite = account_state.get("quant_model_suite") or account_state.get(
        "quant_model_suite_validation"
    )
    if not isinstance(suite, dict):
        return {"decision": "pass", "reason": "quant suite unavailable"}
    raw_models = suite.get("models") or suite.get("model_votes") or suite.get("results") or []
    votes = []
    for row in raw_models if isinstance(raw_models, list) else []:
        if not isinstance(row, dict):
            continue
        decision = str(
            row.get("decision")
            or row.get("recommendation")
            or row.get("prediction_decision")
            or row.get("vote")
            or ""
        ).lower()
        provider = str(row.get("provider") or row.get("model") or row.get("name") or "")
        if decision in {"block", "avoid", "sell", "short", "negative", "veto"}:
            votes.append(("negative", provider))
        elif decision in {"allow", "buy", "pass", "positive", "support"}:
            votes.append(("positive", provider))
    if not votes:
        majority = str(suite.get("majority_decision") or suite.get("decision") or "").lower()
        if majority in {"block", "avoid", "negative", "veto"}:
            return {
                "decision": "block",
                "reason": f"quant suite majority veto: {majority}",
                "evidence": suite,
            }
        return {"decision": "pass", "reason": "quant suite has no usable votes"}
    negatives = [provider for vote, provider in votes if vote == "negative"]
    positives = [provider for vote, provider in votes if vote == "positive"]
    asymmetric_negative = any("asymmetric" in provider for provider in negatives)
    if len(negatives) > len(positives):
        return {
            "decision": "block" if asymmetric_negative else "size_down",
            "reason": (
                "quant suite majority disagreement: "
                f"negative={len(negatives)} positive={len(positives)} "
                f"asymmetric_negative={asymmetric_negative}"
            ),
            "evidence": {
                "negative_models": negatives,
                "positive_models": positives,
                "source": suite,
            },
        }
    return {
        "decision": "pass",
        "reason": (
            "quant suite majority is not negative: "
            f"negative={len(negatives)} positive={len(positives)}"
        ),
    }


def _historical_bar_regime_gate(symbol, account_state):
    intelligence = account_state.get("historical_bar_model_intelligence") or {}
    if not isinstance(intelligence, dict):
        return {"decision": "pass", "reason": "historical-bar intelligence unavailable"}
    symbol_u = str(symbol or "").upper()
    blockers = []
    matched = []
    for label in intelligence.get("labels") or []:
        if not isinstance(label, dict):
            continue
        for gate in label.get("symbol_gates") or []:
            if not isinstance(gate, dict):
                continue
            if str(gate.get("symbol") or "").upper() != symbol_u:
                continue
            matched.append(gate)
            blockers.extend(str(item) for item in gate.get("blockers") or [])
    if not matched:
        return {"decision": "pass", "reason": "no symbol-level historical-bar gate"}
    if blockers:
        toxicity_block = any("vpin_toxicity" in item for item in blockers)
        return {
            "decision": "block" if toxicity_block else "size_down",
            "reason": ("historical-bar symbol gate failed: " + ", ".join(blockers[:4])),
            "evidence": matched,
        }
    return {"decision": "pass", "reason": "historical-bar symbol gate passed"}


def _strategy_memory_distribution_gate(account_state):
    health = evaluate_strategy_memory_distribution_health(account_state=account_state)
    action = str(health.get("decision") or "pass").lower()
    if action == "size_down":
        return {
            "decision": "size_down",
            "reason": health.get("reason") or "strategy-memory distribution drift",
            "evidence": health,
        }
    if action == "caution":
        return {
            "decision": "caution",
            "reason": health.get("reason") or "strategy-memory distribution caution",
            "evidence": health,
        }
    return {"decision": "pass", "reason": health.get("reason") or "distribution stable"}


def _confidence_calibration_gate(account_state):
    calibrated = account_state.get("calibrated_confidence")
    if not isinstance(calibrated, dict):
        return {"decision": "pass", "reason": "calibrated confidence unavailable"}

    candidates = []
    primary_predicted = _to_float(calibrated.get("primary_predicted_win_rate"))
    primary_realized = _to_float(calibrated.get("primary_realized_win_rate"))
    primary_sample = _to_float(calibrated.get("primary_sample_size")) or 0
    if primary_predicted is not None and primary_realized is not None:
        candidates.append(
            {
                "source": calibrated.get("primary_source") or "primary",
                "sample_size": primary_sample,
                "calibration_error": abs(primary_predicted - primary_realized),
            }
        )
    for source, payload in (calibrated.get("sources") or {}).items():
        if not isinstance(payload, dict):
            continue
        error = _to_float(payload.get("calibration_error"))
        sample = _to_float(payload.get("sample_size")) or 0
        if error is None:
            continue
        candidates.append(
            {
                "source": source,
                "sample_size": sample,
                "calibration_error": error,
            }
        )

    qualified = [row for row in candidates if row["sample_size"] >= 20]
    if not qualified:
        return {"decision": "pass", "reason": "no sampled calibration error"}
    worst = max(qualified, key=lambda row: row["calibration_error"])
    if worst["calibration_error"] >= 0.15:
        return {
            "decision": "size_down",
            "reason": (
                "confidence calibration drift: "
                f"source={worst['source']} error={worst['calibration_error']:.3f} "
                f"sample={int(worst['sample_size'])}"
            ),
            "evidence": {
                "worst_source": worst["source"],
                "calibration_error": round(worst["calibration_error"], 4),
                "sample_size": int(worst["sample_size"]),
                "size_multiplier": 0.65,
            },
        }
    if worst["calibration_error"] >= 0.10:
        return {
            "decision": "caution",
            "reason": (
                "confidence calibration warning: "
                f"source={worst['source']} error={worst['calibration_error']:.3f} "
                f"sample={int(worst['sample_size'])}"
            ),
            "evidence": {
                "worst_source": worst["source"],
                "calibration_error": round(worst["calibration_error"], 4),
                "sample_size": int(worst["sample_size"]),
                "size_multiplier": 0.85,
            },
        }
    return {"decision": "pass", "reason": "confidence calibration within tolerance"}


def evaluate_decision_policy(
    symbol,
    action,
    intelligence_context=None,
    account_state=None,
    strategy_memory_override=None,
):
    intelligence_context = intelligence_context or {}
    account_state = account_state if isinstance(account_state, dict) else {}
    if "market_regime" not in account_state:
        account_state["market_regime"] = classify_market_regime(
            account_state=account_state,
            market_context=account_state.get("market_alignment") or {},
        ).to_dict()
    if "portfolio_decision" not in account_state:
        account_state["portfolio_decision"] = evaluate_portfolio_decision(
            symbol=symbol,
            action=action,
            account_state=account_state,
        ).to_dict()
    if "execution_quality" not in account_state:
        account_state["execution_quality"] = estimate_execution_quality(
            symbol=symbol,
            action=action,
            signal_price=account_state.get("signal_price"),
            account_state=account_state,
        ).to_dict()
    if not isinstance(account_state.get("calibrated_confidence"), dict):
        account_state["calibrated_confidence"] = build_calibrated_confidence(
            account_state=account_state,
            context=intelligence_context,
        ).to_dict()
    account_state.setdefault("rollout_contract", telemetry_only_rollout_contract())
    utility_estimate = estimate_decision_utility(
        action=action,
        intelligence_context=intelligence_context,
        account_state=account_state,
    ).to_dict()

    if action != "buy":
        return {
            "decision": "allow",
            "size_multiplier": 1.0,
            "reason": "sell signal bypasses buy-side decision policy",
            "authority_scope": "sell_passthrough_no_order_authority",
            "can_increase_size": False,
            "can_submit_orders": False,
            "evidence": [],
            "utility_estimate": utility_estimate,
        }

    hard_gate = _hard_gate_block(account_state)
    if hard_gate:
        return {
            "decision": "block",
            "size_multiplier": 0.0,
            "reason": f"hard gate context in account_state: {hard_gate}",
            "authority_scope": "hard_gate_mirror_for_replay_audit",
            "can_increase_size": False,
            "can_submit_orders": False,
            "evidence": [hard_gate],
            "risks": [hard_gate],
            "supports": [],
            "learned_min_score": None,
            "worst_memory_recommendation": None,
            "memory_matches": [],
            "utility_estimate": utility_estimate,
        }

    evidence = []
    risks = []
    supports = []

    summary = intelligence_context.get("summary") or {}
    recommended_action = summary.get("recommended_action")

    if recommended_action:
        evidence.append(f"intelligence_context recommended_action={recommended_action}")

    if recommended_action == "block_preferred":
        risks.append("intelligence context prefers block")
    elif recommended_action == "size_down":
        risks.append("intelligence context recommends size down")
    elif recommended_action == "caution":
        risks.append("intelligence context recommends caution")
    elif recommended_action == "allow":
        supports.append("intelligence context allows")

    opportunity = (
        intelligence_context.get("opportunity_score_0_100")
        or account_state.get("opportunity_score_0_100")
        or intelligence_context.get("opportunity_score")
        or account_state.get("opportunity_score")
        or {}
    )
    opp_score = _normalize_score(opportunity.get("score"))
    opp_decision = opportunity.get("decision")

    if opp_score is not None:
        evidence.append(f"opportunity_score={opp_score:.1f}")

    if opp_decision == "block":
        risks.append("opportunity score blocks")
    elif opp_decision in ("watch", "size_down"):
        risks.append(f"opportunity score decision={opp_decision}")
    elif opp_decision in ("allow", "pass"):
        supports.append("opportunity score allows")

    prediction = intelligence_context.get("prediction") or {}
    pred_decision = prediction.get("prediction_decision")
    pred_score = prediction.get("prediction_score")

    if pred_decision:
        evidence.append(f"prediction_decision={pred_decision} score={pred_score}")

    if pred_decision == "block":
        risks.append("prediction gate says block")
    elif pred_decision == "watch":
        risks.append("prediction gate says watch")
    elif pred_decision in ("allow", "pass", "buy"):
        supports.append("prediction supports")

    transformer_authority = account_state.get("transformer_authority")
    if not isinstance(transformer_authority, dict):
        transformer_authority = evaluate_transformer_authority(
            symbol=symbol,
            action=action,
            account_state=account_state,
        )
        account_state["transformer_authority"] = transformer_authority
    transformer_decision = transformer_authority.get("decision")
    transformer_probability = transformer_authority.get("probability")
    if transformer_authority.get("enabled") or transformer_authority.get("model_id"):
        evidence.append(
            "transformer_authority="
            f"{transformer_decision} prob={transformer_probability} mode={transformer_authority.get('mode')}"
        )
    if transformer_decision == "block":
        risks.append(f"transformer authority blocks: {transformer_authority.get('reason')}")
    elif transformer_decision == "size_down":
        risks.append(f"transformer authority sizes down: {transformer_authority.get('reason')}")
    elif transformer_decision == "allow" and transformer_probability is not None:
        supports.append("transformer authority supports/allows")

    calibration_gate = _confidence_calibration_gate(account_state)
    calibration_action = calibration_gate.get("decision")
    if calibration_action == "size_down":
        risks.append(calibration_gate["reason"])
        evidence.append(
            "confidence_calibration=size_down "
            f"error={(calibration_gate.get('evidence') or {}).get('calibration_error')}"
        )
    elif calibration_action == "caution":
        risks.append(calibration_gate["reason"])
        evidence.append(
            "confidence_calibration=caution "
            f"error={(calibration_gate.get('evidence') or {}).get('calibration_error')}"
        )
    elif account_state.get("calibrated_confidence"):
        supports.append("confidence calibration within tolerance")

    shadow_gate = _shadow_divergence_gate(account_state)
    shadow_action = shadow_gate.get("decision")
    if shadow_action == "block":
        risks.append(shadow_gate["reason"])
        evidence.append(
            "shadow_prediction_health="
            f"{(shadow_gate.get('evidence') or {}).get('status')} "
            f"divergence_rate={(shadow_gate.get('evidence') or {}).get('divergence_rate')}"
        )
    elif shadow_action == "pass" and account_state.get("shadow_prediction_health"):
        supports.append("shadow/live model agreement within tolerance")

    quant_gate = _quant_suite_gate(account_state)
    quant_action = quant_gate.get("decision")
    if quant_action == "block":
        risks.append(quant_gate["reason"])
        evidence.append("quant_model_suite=majority_block")
    elif quant_action == "size_down":
        risks.append(quant_gate["reason"])
        evidence.append("quant_model_suite=majority_size_down")
    elif account_state.get("quant_model_suite"):
        supports.append("quant model suite does not veto")

    historical_gate = _historical_bar_regime_gate(symbol, account_state)
    historical_action = historical_gate.get("decision")
    if historical_action == "block":
        risks.append(historical_gate["reason"])
        evidence.append("historical_bar_symbol_gate=block")
    elif historical_action == "size_down":
        risks.append(historical_gate["reason"])
        evidence.append("historical_bar_symbol_gate=size_down")
    elif account_state.get("historical_bar_model_intelligence"):
        supports.append("historical-bar symbol gate passed")

    distribution_gate = _strategy_memory_distribution_gate(account_state)
    distribution_action = distribution_gate.get("decision")
    account_state["strategy_memory_distribution_health"] = distribution_gate.get("evidence") or {}
    if distribution_action == "size_down":
        risks.append(distribution_gate["reason"])
        evidence.append(
            "strategy_memory_distribution_health=size_down "
            f"max_psi={account_state['strategy_memory_distribution_health'].get('max_psi')}"
        )
    elif distribution_action == "caution":
        risks.append(distribution_gate["reason"])
        evidence.append(
            "strategy_memory_distribution_health=caution "
            f"max_psi={account_state['strategy_memory_distribution_health'].get('max_psi')}"
        )
    elif account_state.get("strategy_memory_distribution_health"):
        supports.append("strategy memory distribution health stable")

    session_gate = intelligence_context.get("session_momentum_gate") or {}
    if session_gate.get("would_block"):
        risks.append(f"session momentum gate would block: {session_gate.get('reason')}")
    elif session_gate.get("severity") in ("pass", "supportive"):
        supports.append("session momentum supportive")

    portfolio_decision = account_state.get("portfolio_decision") or {}
    portfolio_action = portfolio_decision.get("decision")
    if portfolio_action == "block":
        risks.append("portfolio duplicate risk says block")
        evidence.append(
            f"portfolio_duplicate_risk={portfolio_decision.get('duplicate_risk_score')}"
        )
    elif portfolio_action == "size_down":
        risks.append("portfolio duplicate risk says size_down")
        evidence.append(
            f"portfolio_duplicate_risk={portfolio_decision.get('duplicate_risk_score')}"
        )
    elif portfolio_action == "allow":
        supports.append("portfolio duplicate risk acceptable")

    execution_quality = account_state.get("execution_quality") or {}
    execution_action = execution_quality.get("decision")
    if execution_action == "block":
        risks.append("execution quality says block candidate")
        evidence.append(f"net_execution_cost_pct={execution_quality.get('net_execution_cost_pct')}")
    elif execution_action == "size_down":
        risks.append("execution quality says size_down")
        evidence.append(f"net_execution_cost_pct={execution_quality.get('net_execution_cost_pct')}")
    elif execution_action == "allow":
        supports.append("execution quality acceptable")

    # Learned/contextual memory. strategy_memory_override injects a point-in-time
    # archived dict instead of the live strategy_memory.json (used by replay tools).
    memory = contextual_memory_for_signal(
        symbol, intelligence_context, memory_override=strategy_memory_override
    )
    memory_matches = memory.get("matches") or []

    recs = [m.get("recommendation") for m in memory_matches]
    worst_rec = _worst_recommendation(recs)

    learned_min_scores = [
        int(m["min_setup_score"])
        for m in memory_matches
        if isinstance(m.get("min_setup_score"), int)
    ]
    learned_min_score = max(learned_min_scores) if learned_min_scores else None

    if memory_matches:
        evidence.append(
            "strategy_memory_matches="
            + ",".join(f"{m.get('label')}:{m.get('recommendation')}" for m in memory_matches[:6])
        )

    if worst_rec == "avoid":
        risks.append("strategy memory has avoid recommendation")
    elif worst_rec == "caution":
        risks.append("strategy memory has caution recommendation")
    elif worst_rec == "favor":
        supports.append("strategy memory favors this context")

    # Determine final policy.
    decision = "allow"
    size_multiplier = 1.0
    reason = "decision policy allows"

    # Hard block when learned/contextual threshold says score is insufficient.
    if learned_min_score is not None and opp_score is not None:
        if worst_rec in ("avoid", "caution") and opp_score < learned_min_score:
            decision = "block"
            size_multiplier = 0.0
            reason = (
                f"strategy memory requires score >= {learned_min_score}; "
                f"opportunity_score={opp_score:.1f}; recommendation={worst_rec}"
            )

    # Hard block on strong negative deterministic signals.
    if decision != "block":
        if (
            opp_decision == "block"
            or pred_decision == "block"
            or portfolio_action == "block"
            or execution_action == "block"
            or transformer_decision == "block"
            or shadow_action == "block"
            or quant_action == "block"
            or historical_action == "block"
        ):
            decision = "block"
            size_multiplier = 0.0
            reason = (
                "deterministic policy block: "
                f"opportunity={opp_decision}, prediction={pred_decision}, "
                f"portfolio={portfolio_action}, execution={execution_action}, "
                f"transformer={transformer_decision}, shadow={shadow_action}, "
                f"quant={quant_action}, historical_bar={historical_action}"
            )

    # Intelligence block-preferred becomes live block only if support is weak.
    if decision != "block" and recommended_action == "block_preferred" and len(supports) == 0:
        decision = "block"
        size_multiplier = 0.0
        reason = "intelligence context block_preferred with no supporting evidence"

    # Size down for caution/avoid memory or multiple risks.
    if decision != "block":
        if worst_rec == "avoid":
            decision = "size_down"
            size_multiplier = 0.35
            reason = "strategy memory avoid context; allowing only reduced-size Claude review"
        elif worst_rec == "caution" or recommended_action == "size_down":
            decision = "size_down"
            size_multiplier = 0.5
            reason = "cautionary learned/live context; reduce size"
        elif portfolio_action == "size_down":
            decision = "size_down"
            size_multiplier = min(
                0.75,
                float(portfolio_decision.get("size_multiplier") or 0.75),
            )
            reason = "portfolio duplicate risk; reduce size"
        elif execution_action == "size_down":
            decision = "size_down"
            size_multiplier = min(
                0.75,
                float(execution_quality.get("size_multiplier") or 0.75),
            )
            reason = "execution quality cost; reduce size"
        elif transformer_decision == "size_down":
            decision = "size_down"
            size_multiplier = min(
                0.75,
                float(transformer_authority.get("size_multiplier") or 0.75),
            )
            reason = "transformer authority requested reduced size"
        elif calibration_action == "size_down":
            decision = "size_down"
            size_multiplier = min(
                0.75,
                float((calibration_gate.get("evidence") or {}).get("size_multiplier") or 0.75),
            )
            reason = "confidence calibration drift; reduce size"
        elif quant_action == "size_down":
            decision = "size_down"
            size_multiplier = 0.65
            reason = "quant model suite majority disagreement; reduce size"
        elif historical_action == "size_down":
            decision = "size_down"
            size_multiplier = 0.60
            reason = "historical-bar regime/symbol gate requested reduced size"
        elif distribution_action == "size_down":
            decision = "size_down"
            size_multiplier = min(
                0.75,
                float((distribution_gate.get("evidence") or {}).get("size_multiplier") or 0.75),
            )
            reason = "strategy-memory distribution drift; reduce size"
        elif recommended_action == "caution" or len(risks) >= 2:
            decision = "size_down"
            size_multiplier = 0.75
            reason = "multiple caution signals; reduce size"

    return {
        "decision": decision,
        "size_multiplier": size_multiplier,
        "reason": reason,
        "risks": risks[:8],
        "supports": supports[:8],
        "evidence": evidence[:10],
        "learned_min_score": learned_min_score,
        "worst_memory_recommendation": worst_rec,
        "memory_matches": memory_matches[:8],
        "authority_scope": "conservative_buy_review",
        "can_increase_size": False,
        "can_submit_orders": False,
        "utility_estimate": utility_estimate,
        "portfolio_decision": portfolio_decision,
        "execution_quality": execution_quality,
        "transformer_authority": transformer_authority,
        "confidence_calibration_gate": calibration_gate,
        "shadow_prediction_gate": shadow_gate,
        "quant_model_suite_gate": quant_gate,
        "historical_bar_regime_gate": historical_gate,
        "strategy_memory_distribution_gate": distribution_gate,
    }
