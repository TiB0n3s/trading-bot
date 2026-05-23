#!/usr/bin/env python3
"""
Tape reader helpers.

Classifies normalized intraday state into human/trader-readable labels.

This module is pure/read-only. It does not fetch data, approve/reject trades,
or place orders.
"""

from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def classify_tape(state: dict[str, Any]) -> dict[str, Any]:
    """
    Classify intraday state into a tactical tape label.

    Expected state fields come from market_intelligence.intraday_state:
      - trend_label
      - return_5m_pct
      - return_15m_pct
      - return_30m_pct
      - distance_from_vwap_pct
      - distance_from_session_high_pct
      - distance_from_session_low_pct
    """
    trend = state.get("trend_label") or "unknown"
    ret_5m = safe_float(state.get("return_5m_pct"))
    ret_15m = safe_float(state.get("return_15m_pct"))
    ret_30m = safe_float(state.get("return_30m_pct"))
    vwap_dist = state.get("distance_from_vwap_pct")
    high_dist = state.get("distance_from_session_high_pct")
    low_dist = state.get("distance_from_session_low_pct")

    vwap_dist_f = safe_float(vwap_dist) if vwap_dist is not None else None
    high_dist_f = safe_float(high_dist) if high_dist is not None else None
    low_dist_f = safe_float(low_dist) if low_dist is not None else None

    reasons: list[str] = []
    score = 0

    if trend == "rising":
        score += 25
        reasons.append("multi-window tape is rising")
    elif trend == "falling":
        score -= 25
        reasons.append("multi-window tape is falling")
    elif trend == "mixed":
        reasons.append("multi-window tape is mixed")
    else:
        reasons.append("tape trend is unknown")

    if ret_5m > 0.15:
        score += 10
        reasons.append(f"5m momentum positive ({ret_5m:.3f}%)")
    elif ret_5m < -0.15:
        score -= 10
        reasons.append(f"5m momentum negative ({ret_5m:.3f}%)")

    if ret_15m > 0.25:
        score += 10
        reasons.append(f"15m momentum positive ({ret_15m:.3f}%)")
    elif ret_15m < -0.25:
        score -= 10
        reasons.append(f"15m momentum negative ({ret_15m:.3f}%)")

    if vwap_dist_f is not None:
        if -0.20 <= vwap_dist_f <= 0.60:
            score += 10
            reasons.append(f"price is near/above VWAP ({vwap_dist_f:.3f}%)")
        elif vwap_dist_f > 1.50:
            score -= 15
            reasons.append(f"price is extended above VWAP ({vwap_dist_f:.3f}%)")
        elif vwap_dist_f < -0.50:
            score -= 15
            reasons.append(f"price is below VWAP ({vwap_dist_f:.3f}%)")

    if high_dist_f is not None:
        if high_dist_f > -0.25:
            score += 5
            reasons.append(f"price is near session high ({high_dist_f:.3f}%)")
        elif high_dist_f < -1.00:
            score -= 5
            reasons.append(f"price is well below session high ({high_dist_f:.3f}%)")

    if low_dist_f is not None:
        if low_dist_f < 0.25:
            score -= 10
            reasons.append(f"price is near session low ({low_dist_f:.3f}%)")
        elif low_dist_f > 1.00:
            score += 5
            reasons.append(f"price is holding above session low ({low_dist_f:.3f}%)")

    if score >= 35:
        label = "clean_momentum"
        action_hint = "favor_approval_if_other_gates_confirm"
    elif score >= 15:
        label = "constructive_tape"
        action_hint = "acceptable_if_entry_not_extended"
    elif score <= -30:
        label = "fading_or_weak_tape"
        action_hint = "downgrade_or_reject_buy"
    elif vwap_dist_f is not None and vwap_dist_f > 1.50:
        label = "extended_above_vwap"
        action_hint = "avoid_chasing"
    elif vwap_dist_f is not None and vwap_dist_f < -0.50:
        label = "below_vwap"
        action_hint = "caution_or_reject_buy"
    else:
        label = "mixed_tape"
        action_hint = "neutral"

    return {
        "symbol": state.get("symbol"),
        "label": label,
        "score": score,
        "action_hint": action_hint,
        "reasons": reasons,
        "state": state,
    }


def tape_supports_buy(classification: dict[str, Any]) -> bool:
    """Return True when the tape classification supports a buy setup."""
    return classification.get("label") in {
        "clean_momentum",
        "constructive_tape",
    }


def tape_warns_chase(classification: dict[str, Any]) -> bool:
    """Return True when the tape classification warns against chasing."""
    return classification.get("label") in {
        "extended_above_vwap",
        "fading_or_weak_tape",
        "below_vwap",
    }
