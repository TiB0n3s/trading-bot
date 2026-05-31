#!/usr/bin/env python3
"""Tests for volatility-normalized signal feature classification."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.volatility_normalization_service import classify_volatility_normalization


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_gt(actual, minimum, label):
    if not actual > minimum:
        raise AssertionError(f"{label}: expected > {minimum!r}, got {actual!r}")


def assert_lt(actual, maximum, label):
    if not actual < maximum:
        raise AssertionError(f"{label}: expected < {maximum!r}, got {actual!r}")


def test_near_reference_normal_volatility_is_supportive():
    result = classify_volatility_normalization(
        account_state={
            "latest_price": 100.40,
            "volatility_inputs": {
                "entry_reference_price": 100.00,
                "atr_pct": 1.2,
                "realized_volatility_pct": 1.0,
                "move_pct": 0.45,
                "range_percentile": 45,
                "gap_percentile": 35,
                "spread_pct": 0.04,
                "stop_distance_pct": 0.75,
                "expected_adverse_excursion_pct": 0.70,
            },
        }
    )

    assert_equal(result.stretch_state, "near_reference", "stretch")
    assert_equal(result.chase_risk, "normal", "chase risk")
    assert_equal(result.stop_quality, "aligned_with_excursion", "stop")
    assert_gt(result.volatility_adjusted_score, 0.55, "score")
    assert_gt(result.expectancy_modifier, 0.99, "expectancy")


def test_extreme_stretch_and_high_range_percentile_raise_chase_risk():
    result = classify_volatility_normalization(
        account_state={
            "latest_price": 104.50,
            "volatility_inputs": {
                "entry_reference_price": 100.00,
                "atr_pct": 1.0,
                "realized_volatility_pct": 0.9,
                "move_pct": 2.7,
                "range_percentile": 96,
                "gap_percentile": 92,
                "spread_pct": 0.30,
                "stop_distance_pct": 0.35,
                "expected_adverse_excursion_pct": 0.80,
            },
        }
    )

    assert_equal(result.stretch_state, "extreme_stretch", "stretch")
    assert_equal(result.chase_risk, "high", "chase risk")
    assert_equal(result.stop_quality, "too_tight_vs_excursion", "stop")
    assert_gt(result.entry_distance_atr, 4.0, "entry distance atr")
    assert_gt(result.move_zscore, 2.5, "move zscore")
    assert_lt(result.volatility_adjusted_score, 0.20, "score")
    assert_lt(result.expectancy_modifier, 0.70, "expectancy")


def test_missing_inputs_returns_neutral_unknown_state():
    result = classify_volatility_normalization(account_state={})

    assert_equal(result.stretch_state, "unknown", "stretch")
    assert_equal(result.volatility_regime, "unknown", "vol regime")
    assert_equal(result.chase_risk, "normal", "chase")
    assert_equal(result.volatility_adjusted_score, 0.5, "score")


def main():
    tests = [
        test_near_reference_normal_volatility_is_supportive,
        test_extreme_stretch_and_high_range_percentile_raise_chase_risk,
        test_missing_inputs_returns_neutral_unknown_state,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} volatility normalization service tests passed.")


if __name__ == "__main__":
    main()
