#!/usr/bin/env python3
"""
Decision intelligence context builder.

Purpose:
- Normalize scattered live/brief/momentum/setup/learning fields into one object
- Give Claude one clean "trader brain" view
- Keep hard gates in app.py; this module summarizes, it does not place orders
"""

from __future__ import annotations

from portfolio_replacement_memory import load_portfolio_replacement_memory


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _safe_list(value):
    return value if isinstance(value, list) else []


def _compact_dict(d, allowed_keys=None):
    d = _safe_dict(d)
    if allowed_keys is None:
        return {k: v for k, v in d.items() if v is not None}
    return {k: d.get(k) for k in allowed_keys if d.get(k) is not None}


def _summarize_context(ctx):
    """
    Create a plain-English summary and recommended action from existing evidence.

    recommended_action values:
    - allow
    - size_down
    - caution
    - block_preferred

    This summary is advisory. app.py's existing hard gates remain authoritative.
    """
    supports = []
    risks = []

    market = ctx.get("market_brief") or {}
    live_bias = market.get("effective_bias") or market.get("bias")
    if live_bias in ("buy", "live_override_buy"):
        supports.append(f"market bias supportive ({live_bias})")
    elif live_bias in ("avoid", "avoid_soft", "avoid_hard", "live_override_neutral"):
        risks.append(f"market bias caution ({live_bias})")

    prediction = ctx.get("prediction") or {}
    pred_decision = prediction.get("prediction_decision")
    pred_score = prediction.get("prediction_score")
    if pred_decision in ("allow", "buy", "pass"):
        supports.append(f"prediction supports trade ({pred_score})")
    elif pred_decision == "watch":
        risks.append(f"prediction says watch ({pred_score})")
    elif pred_decision == "block":
        risks.append(f"prediction says block ({pred_score})")

    buy_opp = ctx.get("buy_opportunity") or {}
    buy_rec = buy_opp.get("buy_opportunity_recommendation")
    buy_score = buy_opp.get("buy_opportunity_score")
    if buy_rec in ("strong_buy_candidate", "buy_candidate"):
        supports.append(f"buy opportunity supportive ({buy_score})")
    elif buy_rec in ("watch", "small_buy_candidate"):
        risks.append(f"buy opportunity cautious ({buy_score})")
    elif buy_rec == "avoid":
        risks.append(f"buy opportunity avoid ({buy_score})")

    opportunity = ctx.get("opportunity_score") or {}
    opp_decision = opportunity.get("decision")
    opp_score = opportunity.get("score")
    if opp_decision in ("allow", "pass"):
        supports.append(f"opportunity score allows ({opp_score})")
    elif opp_decision in ("watch", "size_down"):
        risks.append(f"opportunity score cautious ({opp_score})")
    elif opp_decision == "block":
        risks.append(f"opportunity score blocks ({opp_score})")

    session_gate = ctx.get("session_momentum_gate") or {}
    if session_gate.get("would_block"):
        risks.append(f"session momentum gate would block: {session_gate.get('reason')}")
    elif session_gate.get("severity") in ("pass", "supportive"):
        supports.append("session momentum supportive")

    rolling = ctx.get("rolling_momentum") or {}
    rolling_direction = rolling.get("direction")
    if rolling_direction == "rising":
        supports.append("rolling momentum rising")
    elif rolling_direction == "falling":
        risks.append("rolling momentum falling")

    session = ctx.get("session_momentum") or {}
    session_label = session.get("trend_label")
    session_score = session.get("trend_score")
    if session_label in ("strong_uptrend", "uptrend", "bullish"):
        supports.append(f"session momentum supportive ({session_label}/{session_score})")
    elif session_label in ("downtrend", "bearish", "weak"):
        risks.append(f"session momentum weak ({session_label}/{session_score})")

    strategy_memory = ctx.get("strategy_memory") or {}
    mem_rec = strategy_memory.get("recommendation")
    if mem_rec == "favor":
        supports.append("strategy memory favors symbol")
    elif mem_rec in ("caution", "avoid"):
        risks.append(f"strategy memory {mem_rec}: {strategy_memory.get('reason')}")

    replacement = ctx.get("portfolio_replacement") or {}
    repl_rec = replacement.get("recommendation")
    if repl_rec in ("replacement_candidate", "replace_now_candidate", "extra_slot_candidate"):
        risks.append(f"portfolio replacement advisory: {repl_rec} - {replacement.get('reason')}")
    elif repl_rec == "observe_only":
        supports.append("portfolio replacement advisory observe_only")

    setup = ctx.get("setup") or {}
    setup_label = setup.get("setup_label")
    setup_policy = setup.get("setup_policy_action")
    if setup_policy in ("allow", "favor"):
        supports.append(f"setup supportive ({setup_label})")
    elif setup_policy in ("block", "avoid"):
        risks.append(f"setup policy caution ({setup_label}/{setup_policy})")

    macro = ctx.get("macro") or {}
    macro_regime = macro.get("macro_regime")
    risk_multiplier = macro.get("risk_multiplier")
    if macro_regime in ("risk_on", "bullish", "normal"):
        supports.append(f"macro supportive ({macro_regime})")
    elif macro_regime in ("caution", "mixed", "neutral"):
        risks.append(f"macro cautious ({macro_regime}, multiplier={risk_multiplier})")
    elif macro_regime in ("defensive", "risk_off", "capital_preservation"):
        risks.append(f"macro defensive ({macro_regime}, multiplier={risk_multiplier})")

    hard_block_indicators = [
        pred_decision == "block",
        opp_decision == "block",
        session_gate.get("would_block") is True,
        setup_policy in ("block", "avoid"),
        live_bias == "avoid_hard",
        mem_rec == "avoid",
    ]

    if any(hard_block_indicators):
        recommended_action = "block_preferred"
    elif len(risks) >= 3 and len(supports) == 0:
        recommended_action = "block_preferred"
    elif len(risks) >= 2:
        recommended_action = "size_down"
    elif len(risks) == 1:
        recommended_action = "caution"
    else:
        recommended_action = "allow"

    return {
        "recommended_action": recommended_action,
        "primary_supports": supports[:5],
        "primary_risks": risks[:5],
        "support_count": len(supports),
        "risk_count": len(risks),
    }


def build_intelligence_context(symbol, action, account_state):
    """
    Build one normalized context object for app.py and Claude.

    This intentionally uses only fields already produced by the live pipeline.
    """
    account_state = _safe_dict(account_state)

    market_brief = {
        "bias": account_state.get("market_bias"),
        "effective_bias": account_state.get("market_bias_effective"),
        "override_reason": account_state.get("market_bias_override_reason"),
        "fundamental_score": account_state.get("fundamental_score"),
        "risk_level": account_state.get("risk_level"),
        "entry_quality": account_state.get("entry_quality"),
    }

    ctx = {
        "symbol": symbol,
        "action": action,
        "market_brief": _compact_dict(market_brief),
        "macro": _compact_dict(account_state.get("macro_risk")),
        "setup": _compact_dict(account_state.get("setup_observation")),
        "live_features": _compact_dict(account_state.get("live_features")),
        "label_features": _compact_dict(account_state.get("label_features")),
        "rolling_momentum": _compact_dict(account_state.get("momentum")),
        "session_momentum": _compact_dict(account_state.get("session_momentum")),
        "session_momentum_gate": _compact_dict(account_state.get("session_momentum_gate")),
        "prediction": _compact_dict(account_state.get("prediction_gate")),
        "buy_opportunity": _compact_dict(account_state.get("buy_opportunity")),
        "opportunity_score": _compact_dict(account_state.get("opportunity_score")),
        "strategy_memory": _compact_dict(account_state.get("strategy_memory")),
        "portfolio_replacement": _compact_dict(load_portfolio_replacement_memory()),
        "correlation_exposure": _safe_list(account_state.get("correlation_exposure")),
    }

    ctx["summary"] = _summarize_context(ctx)
    return ctx
