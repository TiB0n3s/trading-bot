#!/usr/bin/env python3
"""Tests for market participation and relative-strength classification."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.market_participation_service import evaluate_market_participation


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_gt(actual, minimum, label):
    if not actual > minimum:
        raise AssertionError(f"{label}: expected > {minimum!r}, got {actual!r}")


def assert_lt(actual, maximum, label):
    if not actual < maximum:
        raise AssertionError(f"{label}: expected < {maximum!r}, got {actual!r}")


def test_sector_peer_and_index_confirmation_is_supportive():
    result = evaluate_market_participation(
        account_state={
            "market_participation_inputs": {
                "sector_relative_strength_pct": 0.8,
                "industry_group_breadth_pct": 72,
                "peers_above_vwap_pct": 68,
                "peers_above_key_ma_pct": 65,
                "market_breadth_score": 66,
                "index_participation_pct": 70,
                "relative_volume_vs_peers": 1.45,
                "symbol_relative_strength_pct": 1.2,
                "peer_median_relative_strength_pct": 0.4,
                "market_internals": "positive",
            }
        }
    )

    assert_equal(result.participation_state, "confirmed", "participation")
    assert_equal(result.sector_relative_strength_state, "supportive", "sector rs")
    assert_equal(result.peer_confirmation_state, "supportive", "peers")
    assert_equal(result.isolated_move_risk, "low", "isolated risk")
    assert_gt(result.confirmation_score, 0.75, "confirmation score")
    assert_gt(result.expectancy_modifier, 1.0, "expectancy")


def test_isolated_symbol_move_in_weak_group_is_penalized():
    result = evaluate_market_participation(
        account_state={
            "market_participation_inputs": {
                "sector_relative_strength_pct": -0.9,
                "industry_group_breadth_pct": 24,
                "peers_above_vwap_pct": 22,
                "peers_above_key_ma_pct": 30,
                "market_breadth_score": 31,
                "index_participation_pct": 35,
                "relative_volume_vs_peers": 0.55,
                "symbol_relative_strength_pct": 0.6,
                "peer_median_relative_strength_pct": 0.8,
                "market_internals": "negative",
            }
        }
    )

    assert_equal(result.participation_state, "isolated_or_weak", "participation")
    assert_equal(result.peer_confirmation_state, "weak", "peers")
    assert_equal(result.breadth_state, "weak", "breadth")
    assert_equal(result.isolated_move_risk, "high", "isolated risk")
    assert_lt(result.confirmation_score, 0.30, "confirmation score")
    assert_lt(result.expectancy_modifier, 0.80, "expectancy")


def test_missing_inputs_returns_neutral_mixed_state():
    result = evaluate_market_participation(account_state={})

    assert_equal(result.participation_state, "mixed", "participation")
    assert_equal(result.sector_relative_strength_state, "unknown", "sector")
    assert_equal(result.peer_confirmation_state, "unknown", "peers")
    assert_equal(result.confirmation_score, 0.5, "score")


def main():
    tests = [
        test_sector_peer_and_index_confirmation_is_supportive,
        test_isolated_symbol_move_in_weak_group_is_penalized,
        test_missing_inputs_returns_neutral_mixed_state,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} market participation service tests passed.")


if __name__ == "__main__":
    main()
