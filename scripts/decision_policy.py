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

from strategy_constants import DAILY_LOSS_LIMIT_PCT
from strategy_memory import contextual_memory_for_signal

from services.confidence_calibration_service import build_calibrated_confidence
from services.decision_utility_service import estimate_decision_utility
from services.execution_quality_service import estimate_execution_quality
from services.market_regime_service import classify_market_regime
from services.portfolio_decision_service import evaluate_portfolio_decision
from services.rollout_contract_service import telemetry_only_rollout_contract
from services.transformer_authority_model_service import evaluate_transformer_authority

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
            or transformer_decision == "block"
        ):
            decision = "block"
            size_multiplier = 0.0
            reason = (
                "deterministic policy block: "
                f"opportunity={opp_decision}, prediction={pred_decision}, "
                f"portfolio={portfolio_action}, execution={execution_action}, "
                f"transformer={transformer_decision}"
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
        elif execution_action in {"block", "size_down"}:
            decision = "size_down"
            size_multiplier = min(
                0.75,
                float(execution_quality.get("size_multiplier") or 0.75),
            )
            reason = "execution quality cost/block-candidate; reduce size"
        elif transformer_decision == "size_down":
            decision = "size_down"
            size_multiplier = min(
                0.75,
                float(transformer_authority.get("size_multiplier") or 0.75),
            )
            reason = "transformer authority requested reduced size"
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
    }
