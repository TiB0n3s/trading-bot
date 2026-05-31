#!/usr/bin/env python3
"""Tests for observe-only exit decision quality."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.exit_decision_quality_service import evaluate_exit_decision_quality


def test_exit_pressure_rises_on_deterioration_and_thesis_break():
    result = evaluate_exit_decision_quality(
        account_state={
            "exit_decision_inputs": {
                "trend_slope_change_pct": -0.6,
                "relative_strength_change_pct": -0.5,
                "breadth_change_pct": -12,
                "adverse_volatility_expansion": 1.5,
                "holding_minutes": 95,
                "max_expected_holding_minutes": 75,
                "unrealized_pnl_pct": -0.05,
                "thesis_invalidated": True,
                "structure_trail_distance_pct": 0.4,
                "trailing_stop_distance_pct": 0.9,
            }
        }
    )

    assert result.exit_pressure_state == "hard_exit_pressure"
    assert result.thesis_state == "invalidated"
    assert result.recommended_action == "exit_or_tighten_aggressively"
    assert result.exit_quality_score > 0.85


def test_intact_exit_context_recommends_hold():
    result = evaluate_exit_decision_quality(
        account_state={
            "trend": {"direction": "bullish"},
            "exit_decision_inputs": {
                "trend_slope_change_pct": 0.1,
                "relative_strength_change_pct": 0.4,
                "breadth_change_pct": 8,
                "holding_minutes": 20,
                "max_expected_holding_minutes": 90,
                "unrealized_pnl_pct": 0.4,
            },
        }
    )

    assert result.exit_pressure_state == "low_exit_pressure"
    assert result.recommended_action == "hold_with_structure"


def main():
    tests = [
        test_exit_pressure_rises_on_deterioration_and_thesis_break,
        test_intact_exit_context_recommends_hold,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} exit decision quality service tests passed.")


if __name__ == "__main__":
    main()
