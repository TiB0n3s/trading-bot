#!/usr/bin/env python3
"""
Live setup intelligence engine.

This is intentionally deterministic:
- Scores BUY setup quality before Claude
- Can hard-block poor setups pre-Claude
- Produces structured setup context for Claude
- Does not affect SELL signals
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo


BOT_TIMEZONE = ZoneInfo(os.getenv("BOT_TIMEZONE", "America/Chicago"))


def _clamp(value, low=0, high=100):
    return max(low, min(high, value))


def _apply_trend_staleness(direction, strength, last_time_str):
    """Downgrade trend strength when last signal is stale."""
    if not last_time_str:
        return direction, strength
    try:
        ts = datetime.strptime(str(last_time_str), "%Y-%m-%d %H:%M:%S").replace(tzinfo=BOT_TIMEZONE)
        age_hours = (datetime.now(BOT_TIMEZONE) - ts).total_seconds() / 3600.0
    except Exception:
        return direction, strength
    if age_hours > 24:
        return "neutral", "weak"
    if age_hours > 4 and strength == "confirmed":
        return direction, "developing"
    return direction, strength


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_setup(
    symbol,
    signal_price,
    trend=None,
    momentum=None,
    market_bias=None,
    fundamental_score=None,
    risk_level=None,
    entry_quality=None,
    macro_risk=None,
    correlation_exposure=None,
):
    trend = trend or {}
    momentum = momentum or {}
    macro_risk = macro_risk or {}
    correlation_exposure = correlation_exposure or []

    score = 50
    reasons = []

    direction = trend.get("direction")
    strength = trend.get("strength")
    consecutive_count = int(trend.get("consecutive_count") or 0)
    direction, strength = _apply_trend_staleness(direction, strength, trend.get("last_time"))

    # Trend structure
    if direction == "bullish" and strength == "confirmed":
        score += 22
        reasons.append("confirmed bullish trend")
    elif direction == "bullish" and strength == "developing":
        score += 14
        reasons.append("developing bullish trend")
    elif direction == "neutral":
        score -= 14
        reasons.append("neutral trend")
    elif direction == "bearish":
        score -= 38
        reasons.append("bearish trend")

    if consecutive_count >= 5:
        score += 5
        reasons.append(f"{consecutive_count} consecutive confirming signals")
    elif consecutive_count == 3 or consecutive_count == 4:
        score += 2
        reasons.append(f"{consecutive_count} confirming signals")
    elif consecutive_count < 3:
        score -= 8
        reasons.append(f"only {consecutive_count} confirming signals")

    # Momentum / tape read
    momentum_direction = momentum.get("direction")
    momentum_5m = _to_float(momentum.get("momentum_5m_pct", momentum.get("momentum_pct")))
    momentum_15m = _to_float(momentum.get("momentum_15m_pct"))
    price_vs_bars = _to_float(momentum.get("price_vs_bars"))
    premarket_alignment = momentum.get("premarket_alignment")

    if momentum_direction == "rising":
        score += 12
        reasons.append("rising 5m tape")
    elif momentum_direction == "falling":
        score -= 16
        reasons.append("falling 5m tape")
    elif momentum_direction == "flat":
        score -= 3
        reasons.append("flat 5m tape")

    if momentum_5m is not None:
        if momentum_5m >= 0.30:
            score += 6
            reasons.append(f"strong 5m momentum {momentum_5m:.2f}%")
        elif momentum_5m <= -0.20:
            score -= 10
            reasons.append(f"weak 5m momentum {momentum_5m:.2f}%")

    if momentum_15m is not None:
        if momentum_15m >= 0.35:
            score += 8
            reasons.append(f"15m momentum confirms {momentum_15m:.2f}%")
        elif momentum_15m <= -0.25:
            score -= 12
            reasons.append(f"15m momentum negative {momentum_15m:.2f}%")

    if premarket_alignment == "confirmed":
        score += 10
        reasons.append("live tape confirms pre-market thesis")
    elif premarket_alignment == "mixed":
        score -= 5
        reasons.append("mixed pre-market alignment")
    elif premarket_alignment == "contradicted":
        score -= 22
        reasons.append("live tape contradicts pre-market thesis")
    elif premarket_alignment == "bearish_intraday_shift":
        score -= 14
        reasons.append("bearish intraday shift")

    # Entry extension / chase detection
    if price_vs_bars is not None:
        if price_vs_bars > 1.00:
            score -= 24
            reasons.append(f"late/chasing: {price_vs_bars:.2f}% above recent tape")
        elif price_vs_bars > 0.60:
            score -= 16
            reasons.append(f"extended: {price_vs_bars:.2f}% above recent tape")
        elif price_vs_bars > 0.35:
            score -= 8
            reasons.append(f"slightly extended: {price_vs_bars:.2f}% above recent tape")
        elif -0.35 <= price_vs_bars <= 0.20:
            score += 5
            reasons.append("entry near recent tape")

    # Market context
    if market_bias == "buy":
        score += 8
        reasons.append("market brief bias is buy")
    elif market_bias == "avoid":
        score -= 35
        reasons.append("market brief bias is avoid")

    if fundamental_score in ("strong_bullish", "bullish"):
        score += 4
        reasons.append(f"fundamental score {fundamental_score}")
    elif fundamental_score in ("bearish", "strong_bearish"):
        score -= 18
        reasons.append(f"fundamental score {fundamental_score}")

    # Risk and entry quality
    if risk_level == "high":
        score -= 8
        reasons.append("high risk level")
    elif risk_level == "very_high":
        score -= 16
        reasons.append("very high risk level")

    if entry_quality in ("excellent", "high"):
        score += 9
        reasons.append(f"entry quality {entry_quality}")
    elif entry_quality in ("good_on_pullbacks", "good_if_holds_gap", "good_if_breadth_holds"):
        score += 2
        reasons.append(f"conditional quality {entry_quality}")
    elif entry_quality in ("tactical_only", "conditional"):
        score -= 8
        reasons.append(f"tactical/conditional entry {entry_quality}")
    elif entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
        score -= 35
        reasons.append(f"poor/chase entry quality {entry_quality}")

    # Macro regime
    macro_regime = macro_risk.get("macro_regime")
    risk_multiplier = _to_float(macro_risk.get("risk_multiplier"))

    if macro_regime in ("risk_on", "bullish", "normal"):
        score += 5
        reasons.append(f"macro regime {macro_regime}")
    elif macro_regime in ("caution", "mixed", "neutral"):
        score -= 3
        reasons.append(f"macro regime {macro_regime}")
    elif macro_regime in ("defensive", "risk_off"):
        score -= 12
        reasons.append(f"macro regime {macro_regime}")
    elif macro_regime in ("capital_preservation", "panic", "crisis"):
        score -= 45
        reasons.append(f"macro regime {macro_regime}")

    if risk_multiplier is not None and risk_multiplier < 1.0:
        penalty = int((1.0 - risk_multiplier) * 16)
        score -= penalty
        reasons.append(f"macro risk multiplier {risk_multiplier}")

    # Correlation pressure
    for check in correlation_exposure:
        exposure_pct = _to_float(check.get("exposure_pct"))
        limit_pct = _to_float(check.get("limit_pct"))
        cluster = check.get("cluster")
        if exposure_pct is not None and limit_pct is not None and limit_pct > 0:
            utilization = exposure_pct / limit_pct
            if utilization >= 0.90:
                score -= 10
                reasons.append(f"{cluster} cluster near cap")
            elif utilization >= 0.75:
                score -= 5
                reasons.append(f"{cluster} cluster elevated")

    score = _clamp(round(score))

    # Label and recommendation
    if score >= 85:
        label = "premium_momentum_setup"
        recommendation = "favor"
        size_multiplier = 1.00
    elif score >= 70:
        label = "good_confirmed_setup"
        recommendation = "normal"
        size_multiplier = 1.00
    elif score >= 55:
        label = "acceptable_but_cautious"
        recommendation = "caution"
        size_multiplier = 0.75
    elif score >= 40:
        label = "weak_or_late_setup"
        recommendation = "caution"
        size_multiplier = 0.50
    else:
        label = "avoid_low_quality_setup"
        recommendation = "avoid"
        size_multiplier = 0.00

    # Hard-block recommendation. app.py decides whether to enforce this.
    should_block = False
    block_reason = None

    if recommendation == "avoid" or score < 40:
        should_block = True
        block_reason = f"setup score {score} below live minimum"

    # The gray zone can still pass only when the strongest context agrees.
    if 40 <= score < 55:
        strong_exception = (
            direction == "bullish"
            and strength == "confirmed"
            and market_bias == "buy"
            and momentum_direction == "rising"
            and premarket_alignment in ("confirmed", "neutral", None)
        )
        if not strong_exception:
            should_block = True
            block_reason = (
                f"weak setup score {score} without bullish/confirmed + buy bias + rising momentum"
            )

    premarket_alignment_source = (
        "live_tape" if premarket_alignment is not None else "missing_bias"
    )

    return {
        "score": score,
        "label": label,
        "recommendation": recommendation,
        "size_multiplier": size_multiplier,
        "should_block": should_block,
        "block_reason": block_reason,
        "reasons": reasons[:10],
        "premarket_alignment_source": premarket_alignment_source,
        "inputs": {
            "trend_direction": direction,
            "trend_strength": strength,
            "consecutive_count": consecutive_count,
            "momentum_direction": momentum_direction,
            "momentum_5m_pct": momentum_5m,
            "momentum_15m_pct": momentum_15m,
            "price_vs_bars": price_vs_bars,
            "premarket_alignment": premarket_alignment,
            "premarket_alignment_source": premarket_alignment_source,
            "market_bias": market_bias,
            "fundamental_score": fundamental_score,
            "risk_level": risk_level,
            "entry_quality": entry_quality,
            "macro_regime": macro_regime,
            "risk_multiplier": risk_multiplier,
        },
    }
