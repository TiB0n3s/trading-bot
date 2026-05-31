#!/usr/bin/env python3
"""Tests for downside asymmetry scoring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.downside_asymmetry_service import evaluate_downside_asymmetry


def test_high_downside_asymmetry_is_flagged():
    result = evaluate_downside_asymmetry(
        account_state={
            "downside_risk": {
                "gap_down_vulnerability_pct": 2.4,
                "earnings_days": 1,
                "overnight_hold": True,
                "short_interest_pct": 22,
                "headline_sensitivity_score": 0.8,
                "beta": 1.8,
                "historical_setup_mae_pct": -2.2,
                "failure_pattern_signature": "failed_breakout_vwap_loss",
            },
            "market_regime": {"composite_regime": "risk_off_unwind"},
        }
    )

    assert result.downside_state == "asymmetric_downside_high"
    assert result.gap_down_vulnerability == "high"
    assert result.catalyst_risk == "imminent_earnings"
    assert result.expected_adverse_modifier > 1.4


def test_missing_downside_inputs_remains_contained_unknown():
    result = evaluate_downside_asymmetry(account_state={})

    assert result.downside_state == "downside_contained_or_unknown"
    assert result.downside_score == 0.25


def main():
    tests = [
        test_high_downside_asymmetry_is_flagged,
        test_missing_downside_inputs_remains_contained_unknown,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} downside asymmetry service tests passed.")


if __name__ == "__main__":
    main()
