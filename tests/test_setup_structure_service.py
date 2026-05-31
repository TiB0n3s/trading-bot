#!/usr/bin/env python3
"""Tests for structural setup scoring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.setup_structure_service import evaluate_setup_structure


def test_clean_base_with_room_to_supply_scores_high():
    result = evaluate_setup_structure(
        {
            "base_type": "clean",
            "prior_failed_breakouts": 0,
            "compression_ratio": 0.55,
            "expansion_ratio": 1.45,
            "distance_to_resistance_pct": 2.1,
            "distance_to_support_pct": 0.25,
            "anchored_vwap_distance_pct": 0.10,
            "opening_gap_pct": 0.8,
            "gap_hold_pct": 0.7,
            "retest_hold_pct": 0.15,
            "retest_volume_ratio": 0.75,
            "reward_risk_ratio": 2.4,
        }
    )

    assert result.structure_state == "high_quality_structure"
    assert result.base_quality == "clean_base"
    assert result.reward_risk_state == "favorable_rr"
    assert result.structure_score > 0.80


def test_messy_failed_breakout_below_supply_scores_poorly():
    result = evaluate_setup_structure(
        {
            "base_type": "messy",
            "prior_failed_breakouts": 3,
            "distance_to_resistance_pct": 0.20,
            "anchored_vwap_distance_pct": 2.5,
            "opening_gap_pct": 1.4,
            "gap_hold_pct": -0.4,
            "retest_hold_pct": -0.3,
            "reward_risk_ratio": 0.8,
        }
    )

    assert result.structure_state == "poor_structure"
    assert result.failed_breakout_risk == "high"
    assert result.htf_location_state == "crowded_below_supply"
    assert result.structure_score < 0.25


def main():
    tests = [
        test_clean_base_with_room_to_supply_scores_high,
        test_messy_failed_breakout_below_supply_scores_poorly,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} setup structure service tests passed.")


if __name__ == "__main__":
    main()
