# Setup label scores should stay aligned with decision_thresholds.py score bands.
from __future__ import annotations

from typing import Any
from decision_thresholds import SETUP_POLICY_DEFAULTS

HARD_AVOID_LABELS = {
    "avoid_stretched_above_vwap_strength",
    "avoid_far_below_vwap_chase",
    "avoid_below_vwap_weak_drift",
}

FAVORABLE_LABELS = {
    "confirmed_near_vwap_recovery",
    "near_vwap_weak_strength_followthrough",
    "above_vwap_strength_continuation",
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
            "setup_confidence_adjustment": SETUP_POLICY_DEFAULTS["block_confidence_adjustment"],
            "setup_size_multiplier": SETUP_POLICY_DEFAULTS["block_size_multiplier"],
            "reason": f"setup_policy:block:{label}",
        }

    if label in FAVORABLE_LABELS:
        return {
                "setup_policy_action": "boost",
                "setup_confidence_adjustment": SETUP_POLICY_DEFAULTS["boost_confidence_adjustment"],
                "setup_size_multiplier": SETUP_POLICY_DEFAULTS["boost_size_multiplier"],
                "reason": f"setup_policy:boost:{label}",
        }

    if label in WATCH_LABELS:
        return {
                "setup_policy_action": "allow",
                "setup_confidence_adjustment": 0,
                "setup_size_multiplier": SETUP_POLICY_DEFAULTS["neutral_size_multiplier"],
                "reason": f"setup_policy:allow:{label}",
        }

    known_labels = HARD_AVOID_LABELS | FAVORABLE_LABELS | WATCH_LABELS | NEUTRAL_LABELS

    if label and label not in known_labels:
        return {
            "setup_policy_action": "neutral",
            "setup_confidence_adjustment": 0,
            "setup_size_multiplier": SETUP_POLICY_DEFAULTS["neutral_size_multiplier"],
            "reason": f"setup_policy:neutral:unknown_label:{label}",
        }

    return {
        "setup_policy_action": "neutral",
        "setup_confidence_adjustment": 0,
        "setup_size_multiplier": SETUP_POLICY_DEFAULTS["neutral_size_multiplier"],
        "reason": f"setup_policy:neutral:{label or 'unknown'}",
    }