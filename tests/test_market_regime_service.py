#!/usr/bin/env python3
"""Tests for observe-only market regime classification."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.market_regime_service import classify_market_regime


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_gt(actual, minimum, label):
    if not actual > minimum:
        raise AssertionError(f"{label}: expected > {minimum!r}, got {actual!r}")


def assert_lt(actual, maximum, label):
    if not actual < maximum:
        raise AssertionError(f"{label}: expected < {maximum!r}, got {actual!r}")


def test_trend_expansion_boosts_continuation_weights():
    regime = classify_market_regime(
        account_state={
            "macro_risk": {"macro_regime": "risk_on", "risk_multiplier": 1.0},
            "session_momentum": {"trend_label": "strong_uptrend"},
            "momentum": {
                "momentum_state": "accelerating",
                "direction": "rising",
                "volume_state": "surge",
                "volume_surge_ratio": 2.1,
            },
        },
        market_context={"breadth_score": 72, "sector_alignment": "aligned"},
    )

    assert_equal(regime.composite_regime, "trend_expansion", "composite regime")
    assert_equal(regime.trend_regime, "trend_continuation", "trend regime")
    assert_equal(regime.volatility_regime, "high_volatility_expansion", "vol regime")
    assert_gt(
        regime.strategy_weights["trend_continuation"],
        1.2,
        "trend continuation weight",
    )
    assert_gt(regime.strategy_weights["momentum_chase"], 1.0, "momentum chase weight")


def test_liquidity_constrained_regime_penalizes_chase():
    regime = classify_market_regime(
        account_state={
            "macro_risk": {"macro_regime": "neutral", "risk_multiplier": 0.7},
            "session_momentum": {"trend_label": "fading"},
            "momentum": {
                "momentum_state": "flat",
                "direction": "flat",
                "volume_state": "thin",
                "volume_surge_ratio": 0.4,
            },
            "tape": {"classification": "thin"},
            "rolling_momentum": {"special_labels": ["gap_up_chase_risk"]},
        },
        market_context={"breadth_score": 30, "sector_alignment": "misaligned"},
    )

    assert_equal(regime.composite_regime, "liquidity_constrained", "composite regime")
    assert_equal(regime.liquidity_regime, "liquidity_thin", "liquidity regime")
    assert_lt(regime.strategy_weights["momentum_chase"], 0.4, "chase weight")
    assert_gt(regime.strategy_weights["liquidity_sensitivity"], 1.2, "liquidity weight")


def test_missing_inputs_returns_low_confidence_mixed_regime():
    regime = classify_market_regime(account_state={})

    assert_equal(regime.composite_regime, "mixed", "composite regime")
    assert_equal(regime.confidence, "very_low", "confidence")
    assert_equal(regime.strategy_weights["trend_continuation"], 1.0, "default weight")


def main():
    tests = [
        test_trend_expansion_boosts_continuation_weights,
        test_liquidity_constrained_regime_penalizes_chase,
        test_missing_inputs_returns_low_confidence_mixed_regime,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} market regime service tests passed.")


if __name__ == "__main__":
    main()
