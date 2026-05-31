#!/usr/bin/env python3
"""Tests for time-of-day and microstructure feature classification."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.market_microstructure_service import classify_market_microstructure


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_gt(actual, minimum, label):
    if not actual > minimum:
        raise AssertionError(f"{label}: expected > {minimum!r}, got {actual!r}")


def assert_lt(actual, maximum, label):
    if not actual < maximum:
        raise AssertionError(f"{label}: expected < {maximum!r}, got {actual!r}")


def test_opening_gap_acceptance_with_volume_expansion_is_supportive():
    features = classify_market_microstructure(
        account_state={
            "minutes_since_open": 18,
            "latest_price": 104.25,
            "opening_range": {"high": 103.50, "low": 101.25},
            "session_momentum": {
                "opening_gap_pct": 1.2,
                "gap_hold_pct": 0.75,
                "distance_from_vwap_pct": 0.45,
                "range_expansion_ratio": 1.6,
                "bar_overlap_ratio": 0.20,
                "wick_ratio": 0.18,
            },
            "momentum": {"volume_state": "surge", "volume_surge_ratio": 2.1},
        }
    )

    assert_equal(features.session_phase, "first_30m", "session phase")
    assert_equal(features.gap_state, "gap_up_accepted", "gap state")
    assert_equal(
        features.breakout_quality,
        "confirmed_expansion_breakout",
        "breakout quality",
    )
    assert_gt(features.microstructure_score, 0.70, "score")
    assert_gt(features.expectancy_modifier, 1.0, "expectancy modifier")


def test_midday_liquidity_vacuum_breakout_is_penalized():
    features = classify_market_microstructure(
        account_state={
            "minutes_since_open": 210,
            "latest_price": 102.10,
            "opening_range": {"high": 101.75, "low": 100.80},
            "session_momentum": {
                "distance_from_vwap_pct": 1.8,
                "bar_overlap_ratio": 0.72,
                "wick_ratio": 0.62,
                "range_expansion_ratio": 0.55,
            },
            "momentum": {"volume_state": "low", "volume_surge_ratio": 0.4},
        }
    )

    assert_equal(features.session_phase, "midday", "session phase")
    assert_equal(features.liquidity_state, "liquidity_vacuum", "liquidity")
    assert_equal(features.breakout_quality, "liquidity_vacuum_breakout", "breakout")
    assert_equal(features.reversion_risk, "high", "reversion risk")
    assert_lt(features.microstructure_score, 0.30, "score")
    assert_lt(features.expectancy_modifier, 0.75, "expectancy modifier")


def test_power_hour_range_expansion_is_identified():
    features = classify_market_microstructure(
        account_state={
            "minutes_since_open": 335,
            "session_momentum": {
                "range_expansion_ratio": 1.5,
                "distance_from_vwap_pct": 0.35,
            },
            "momentum": {"volume_state": "elevated", "volume_surge_ratio": 1.6},
        }
    )

    assert_equal(features.session_phase, "power_hour", "session phase")
    assert_equal(features.breakout_quality, "power_hour_expansion", "breakout")
    assert_gt(features.expectancy_modifier, 1.0, "expectancy modifier")


def main():
    tests = [
        test_opening_gap_acceptance_with_volume_expansion_is_supportive,
        test_midday_liquidity_vacuum_breakout_is_penalized,
        test_power_hour_range_expansion_is_identified,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} market microstructure service tests passed.")


if __name__ == "__main__":
    main()
