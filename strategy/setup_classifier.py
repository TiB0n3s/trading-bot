#!/usr/bin/env python3
"""
Setup classifier.

Classifies a scored trade thesis and optional tape context into a concise
trader-readable setup label.

This module is pure/read-only. It does not approve, reject, size, or place
orders.
"""

from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def classify_setup(
    thesis: dict[str, Any],
    tape: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Classify a trade thesis into a setup label.

    Expected thesis shape is TradeThesis.to_dict().
    Tape shape is tape_reader.classify_tape().
    """
    tape = tape or {}

    score = safe_float(thesis.get("score"))
    market_bias = thesis.get("market_bias")
    risk_level = thesis.get("risk_level")
    entry_quality = thesis.get("entry_quality")
    trend_direction = thesis.get("trend_direction")
    trend_strength = thesis.get("trend_strength")
    benchmark_aligned = thesis.get("benchmark_aligned")
    approved_by_scorer = bool(thesis.get("approved_by_scorer"))

    positive_factors = thesis.get("positive_factors") or []
    risk_factors = thesis.get("risk_factors") or []

    tape_label = tape.get("label")
    tape_hint = tape.get("action_hint")

    reasons: list[str] = []

    if risk_level == "very_high":
        reasons.append("very_high risk level")

    if market_bias == "avoid":
        reasons.append("market bias avoid")

    if entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
        reasons.append(f"entry_quality={entry_quality}")

    if tape_label in ("extended_above_vwap", "below_vwap", "fading_or_weak_tape"):
        reasons.append(f"tape_label={tape_label}")

    if tape_hint in ("avoid_chasing", "downgrade_or_reject_buy", "caution_or_reject_buy"):
        reasons.append(f"tape_hint={tape_hint}")

    # Strong negative cases first.
    if market_bias == "avoid":
        label = "avoid_or_wait"
        posture = "block_candidate"
    elif entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
        label = "extended_chase_risk"
        posture = "wait_for_pullback"
    elif tape_label == "fading_or_weak_tape":
        label = "weak_tape"
        posture = "wait_or_reject"
    elif tape_label == "below_vwap":
        label = "below_vwap_caution"
        posture = "wait_for_reclaim"
    elif tape_label == "extended_above_vwap":
        label = "extended_above_vwap"
        posture = "avoid_chasing"

    # Constructive cases.
    elif (
        approved_by_scorer
        and trend_direction == "bullish"
        and trend_strength == "confirmed"
        and tape_label in ("clean_momentum", "constructive_tape", None)
        and benchmark_aligned is not False
    ):
        label = "trend_continuation"
        posture = "qualified"

    elif (
        approved_by_scorer
        and trend_direction == "bullish"
        and trend_strength == "developing"
        and tape_label in ("clean_momentum", "constructive_tape", None)
    ):
        label = "developing_momentum"
        posture = "qualified_or_watch"

    elif (
        score >= 55
        and entry_quality in ("good_on_pullbacks", "good_if_holds_gap", "good_if_breadth_holds")
    ):
        label = "conditional_pullback_entry"
        posture = "watch_for_confirmation"

    elif score >= 70:
        label = "qualified_trade"
        posture = "qualified"

    elif score >= 55:
        label = "watchlist_only"
        posture = "watch"

    else:
        label = "reject_or_wait"
        posture = "wait"

    return {
        "label": label,
        "posture": posture,
        "score": score,
        "market_bias": market_bias,
        "risk_level": risk_level,
        "entry_quality": entry_quality,
        "trend": f"{trend_direction}/{trend_strength}",
        "tape_label": tape_label,
        "positive_factor_count": len(positive_factors),
        "risk_factor_count": len(risk_factors),
        "reasons": reasons,
    }
