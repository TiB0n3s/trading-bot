#!/usr/bin/env python3
"""
Deterministic trade scoring engine.

Observe-only at first. This produces a structured score and thesis from
market context, trend, momentum, macro, and execution-quality fields.

It does not place orders.
"""

from __future__ import annotations

from typing import Any

from market_intelligence.market_state import load_market_context, macro_regime, symbol_context
from strategy.trade_thesis import TradeThesis


APPROVAL_THRESHOLD = 70.0
WATCHLIST_THRESHOLD = 55.0


def _add(score: float, amount: float, factors: list[str], label: str) -> float:
    factors.append(label)
    return score + amount


def _penalize(score: float, amount: float, factors: list[str], label: str) -> float:
    factors.append(label)
    return score - amount


def score_trade(
    symbol: str,
    action: str,
    account_state: dict[str, Any] | None = None,
    trend: dict[str, Any] | None = None,
    momentum: dict[str, Any] | None = None,
    market_alignment: dict[str, Any] | None = None,
    tape: dict[str, Any] | None = None,
) -> TradeThesis:
    """
    Return a TradeThesis for the proposed signal.

    Inputs are intentionally plain dicts so this can be called from app.py
    later without forcing a larger refactor.
    """
    symbol = symbol.upper()
    action = action.lower()
    account_state = account_state or {}
    trend = trend or {}
    momentum = momentum or {}
    market_alignment = market_alignment or {}
    tape = tape or account_state.get("tape") or {}

    ctx = load_market_context()
    regime = macro_regime(ctx)
    sym_ctx = symbol_context(symbol, ctx)

    score = 50.0
    positive: list[str] = []
    risks: list[str] = []

    # Sells are handled by risk-reduction logic in the current bot.
    # The scorer focuses primarily on buy quality.
    if action == "sell":
        return TradeThesis(
            symbol=symbol,
            action=action,
            approved_by_scorer=True,
            score=100.0,
            setup_type="risk_reduction_or_exit",
            macro_regime=regime,
            market_bias=sym_ctx.get("bias"),
            fundamental_score=sym_ctx.get("fundamental_score"),
            risk_level=sym_ctx.get("risk_level"),
            entry_quality=sym_ctx.get("entry_quality"),
            trend_direction=trend.get("direction"),
            trend_strength=trend.get("strength"),
            momentum_direction=momentum.get("direction"),
            momentum_pct=momentum.get("momentum_pct"),
            benchmark=market_alignment.get("benchmark"),
            benchmark_aligned=market_alignment.get("aligned_for_buy"),
            positive_factors=["sell signals remain allowed for risk reduction"],
            reason="Sell/exit signal scored as allowed because it can reduce exposure.",
        )

    # Macro regime.
    if regime in ("risk_on", "bullish", "normal"):
        score = _add(score, 10, positive, f"macro regime supportive: {regime}")
    elif regime in ("caution", "mixed", "neutral"):
        score = _penalize(score, 5, risks, f"macro regime cautious: {regime}")
    elif regime in ("defensive", "risk_off"):
        score = _penalize(score, 15, risks, f"macro regime defensive: {regime}")
    elif regime in ("capital_preservation", "panic", "crisis"):
        score = _penalize(score, 40, risks, f"macro regime blocks risk: {regime}")
    else:
        score = _penalize(score, 8, risks, f"macro regime unknown: {regime}")

    # Market brief bias.
    bias = sym_ctx.get("bias")
    if bias == "buy":
        score = _add(score, 12, positive, "market brief bias is buy")
    elif bias == "avoid":
        score = _penalize(score, 35, risks, "market brief bias is avoid")
    elif bias == "neutral":
        score = _penalize(score, 3, risks, "market brief bias is neutral")

    # Fundamental score.
    fundamental = sym_ctx.get("fundamental_score")
    if fundamental == "strong_bullish":
        score = _add(score, 10, positive, "fundamental score strong_bullish")
    elif fundamental == "bullish":
        score = _add(score, 5, positive, "fundamental score bullish")
    elif fundamental in ("bearish", "strong_bearish"):
        score = _penalize(score, 25, risks, f"fundamental score {fundamental}")

    # Trend.
    direction = trend.get("direction")
    strength = trend.get("strength")
    count = int(trend.get("consecutive_count") or 0)

    if direction == "bullish" and strength == "confirmed":
        score = _add(score, 18, positive, f"bullish confirmed trend count={count}")
    elif direction == "bullish" and strength == "developing":
        score = _add(score, 10, positive, f"bullish developing trend count={count}")
    elif direction == "neutral":
        score = _penalize(score, 10, risks, f"neutral trend count={count}")
    elif direction == "bearish":
        score = _penalize(score, 30, risks, f"bearish trend count={count}")

    # Momentum.
    mom_dir = momentum.get("direction")
    mom_pct = momentum.get("momentum_pct")
    if mom_dir == "rising":
        score = _add(score, 8, positive, f"rising momentum {mom_pct}%")
    elif mom_dir == "falling":
        score = _penalize(score, 10, risks, f"falling momentum {mom_pct}%")
    elif mom_dir == "flat":
        score = _penalize(score, 2, risks, "flat momentum")

    # Premarket/live alignment if present.
    premarket_alignment = momentum.get("premarket_alignment")
    if premarket_alignment == "confirmed":
        score = _add(score, 8, positive, "premarket thesis confirmed by tape")
    elif premarket_alignment == "contradicted":
        score = _penalize(score, 15, risks, "premarket thesis contradicted by tape")
    elif premarket_alignment == "mixed":
        score = _penalize(score, 5, risks, "premarket/live alignment mixed")

    # Benchmark / market alignment.
    aligned = market_alignment.get("aligned_for_buy")
    if aligned is True:
        score = _add(score, 8, positive, "benchmark/market alignment supportive")
    elif aligned is False:
        score = _penalize(score, 15, risks, "benchmark/market alignment not supportive")

    # Intraday tape classification.
    tape_label = tape.get("label")
    tape_score = tape.get("score")
    tape_hint = tape.get("action_hint")

    if tape_label == "clean_momentum":
        score = _add(score, 10, positive, "tape classification clean_momentum")
    elif tape_label == "constructive_tape":
        score = _add(score, 6, positive, "tape classification constructive_tape")
    elif tape_label == "extended_above_vwap":
        score = _penalize(score, 10, risks, "tape warns extended_above_vwap")
    elif tape_label == "below_vwap":
        score = _penalize(score, 12, risks, "tape below_vwap")
    elif tape_label == "fading_or_weak_tape":
        score = _penalize(score, 18, risks, "tape fading_or_weak_tape")
    elif tape_label == "mixed_tape":
        score = _penalize(score, 3, risks, "tape mixed_tape")

    if tape_hint in ("avoid_chasing", "downgrade_or_reject_buy", "caution_or_reject_buy"):
        risks.append(f"tape action_hint={tape_hint}")

    if tape_score is not None:
        if tape_score >= 35:
            positive.append(f"tape_score strong ({tape_score})")
        elif tape_score <= -30:
            risks.append(f"tape_score weak ({tape_score})")

    # Risk level.
    risk_level = sym_ctx.get("risk_level")
    if risk_level == "low":
        score = _add(score, 3, positive, "risk level low")
    elif risk_level == "high":
        score = _penalize(score, 8, risks, "risk level high")
    elif risk_level == "very_high":
        score = _penalize(score, 18, risks, "risk level very_high")

    # Entry quality.
    entry_quality = sym_ctx.get("entry_quality")
    if entry_quality in ("excellent", "high"):
        score = _add(score, 8, positive, f"entry quality {entry_quality}")
    elif entry_quality in ("good_on_pullbacks", "good_if_holds_gap", "good_if_breadth_holds"):
        score = _add(score, 3, positive, f"conditional quality {entry_quality}")
        risks.append("entry requires confirmation")
    elif entry_quality in ("tactical_only", "conditional", "hedge_only"):
        score = _penalize(score, 8, risks, f"entry quality {entry_quality}")
    elif entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
        score = _penalize(score, 25, risks, f"entry quality {entry_quality}")

    score = max(0.0, min(100.0, round(score, 2)))
    approved = score >= APPROVAL_THRESHOLD

    if score >= APPROVAL_THRESHOLD:
        setup_type = "qualified_trade"
    elif score >= WATCHLIST_THRESHOLD:
        setup_type = "watchlist_only"
    else:
        setup_type = "reject_or_wait"

    reason = (
        f"score={score}; "
        f"positives={len(positive)}; "
        f"risks={len(risks)}; "
        f"setup={setup_type}"
    )

    return TradeThesis(
        symbol=symbol,
        action=action,
        approved_by_scorer=approved,
        score=score,
        setup_type=setup_type,
        macro_regime=regime,
        market_bias=bias,
        fundamental_score=fundamental,
        risk_level=risk_level,
        entry_quality=entry_quality,
        trend_direction=direction,
        trend_strength=strength,
        momentum_direction=mom_dir,
        momentum_pct=mom_pct,
        benchmark=market_alignment.get("benchmark"),
        benchmark_aligned=aligned,
        risk_factors=risks,
        positive_factors=positive,
        reason=reason,
    )
