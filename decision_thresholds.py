from __future__ import annotations

PREDICTION_GATE_THRESHOLDS = {
    "pass_min_score": 6,
    "watch_min_score": 4,
}

SETUP_POLICY_DEFAULTS = {
    "block_confidence_adjustment": -20,
    "boost_confidence_adjustment": 10,
    "boost_size_multiplier": 1.10,
    "neutral_size_multiplier": 1.0,
    "block_size_multiplier": 0.0,
}

SETUP_SCORE_BANDS = {
    "strong_avoid_max": 20,
    "weak_avoid_max": 35,
    "neutral_max": 55,
    "watch_min": 56,
    "favorable_min": 70,
}