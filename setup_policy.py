#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


HARD_AVOID_LABELS = {
    "avoid_stretched_above_vwap_strength",
    "avoid_far_below_vwap_chase",
    "avoid_below_vwap_weak_drift",
}

FAVORABLE_LABELS = {
    "confirmed_near_vwap_recovery",
    "near_vwap_weak_strength_followthrough",
}

WATCH_LABELS = {
    "oversold_weak_bounce_watch",
    "oversold_neutral_rebound_watch",
    "neutral_near_vwap_balanced",
}

NEUTRAL_LABELS = {
    "above_vwap_neutral_continuation",
    "below_vwap_neutral_drift_risk",
    "balanced_transition_state",
    "unclassified_transition",
    "late_strength_near_vwap_risk",
    "above_vwap_strength_continuation",
    "far_below_vwap_weakness",
    "stable_near_vwap_strength",
}


def evaluate_setup_policy(setup_label: str | None) -> dict[str, Any]:
    label = (setup_label or "").strip()

    if label in HARD_AVOID_LABELS:
        return {
            "setup_policy_action": "block",
            "setup_confidence_adjustment": -20,
            "setup_size_multiplier": 0.0,
            "reason": f"setup_policy:block:{label}",
        }

    if label in FAVORABLE_LABELS:
        return {
            "setup_policy_action": "boost",
            "setup_confidence_adjustment": 10,
            "setup_size_multiplier": 1.10,
            "reason": f"setup_policy:boost:{label}",
        }

    if label in WATCH_LABELS:
        return {
            "setup_policy_action": "allow",
            "setup_confidence_adjustment": 0,
            "setup_size_multiplier": 1.0,
            "reason": f"setup_policy:allow:{label}",
        }

    return {
        "setup_policy_action": "neutral",
        "setup_confidence_adjustment": 0,
        "setup_size_multiplier": 1.0,
        "reason": f"setup_policy:neutral:{label or 'unknown'}",
    }