#!/usr/bin/env python3
"""Tests for holistic decision quality review labels."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.decision_quality_review_service import (
    build_decision_quality_review_payload,
)


def test_decision_quality_review_grades_entries_exits_and_misses():
    payload = build_decision_quality_review_payload(
        [
            {
                "decision_time": "2026-06-03T10:00:00-04:00",
                "symbol": "AAPL",
                "approved": 1,
                "final_decision": "approved",
                "realized_return_pct": 0.90,
                "mfe_pct": 1.10,
                "capture_ratio": 0.82,
                "setup_label": "clean_breakout",
                "symbol_pattern": "trend_continuation_with_participation",
            },
            {
                "decision_time": "2026-06-03T10:10:00-04:00",
                "symbol": "MSFT",
                "approved": 1,
                "final_decision": "approved",
                "realized_return_pct": -0.05,
                "mfe_pct": 0.75,
                "capture_ratio": -0.07,
                "missed_upside_pct": 0.80,
                "setup_label": "near_vwap_recovery",
                "symbol_pattern": "constructive_pullback",
            },
            {
                "decision_time": "2026-06-03T10:20:00-04:00",
                "symbol": "META",
                "approved": 1,
                "final_decision": "approved",
                "realized_return_pct": -0.65,
                "mfe_pct": 0.08,
                "max_adverse_excursion_pct": -0.90,
                "setup_label": "messy_range",
                "symbol_pattern": "chop_breakout_failure",
            },
            {
                "decision_time": "2026-06-03T10:30:00-04:00",
                "symbol": "NVDA",
                "approved": 0,
                "final_decision": "rejected",
                "rejection_reason": "trend_confirmation",
                "rejected_return_60m": 0.55,
                "rejected_max_favorable_60m": 1.25,
                "setup_label": "clean_breakout",
                "symbol_pattern": "trend_continuation_with_participation",
            },
            {
                "decision_time": "2026-06-03T10:40:00-04:00",
                "symbol": "TSLA",
                "approved": 0,
                "final_decision": "rejected",
                "rejection_reason": "prediction_gate",
                "rejected_return_60m": -0.70,
                "rejected_max_favorable_60m": 0.10,
                "rejected_max_adverse_60m": -1.10,
                "setup_label": "weak_chase",
                "symbol_pattern": "momentum_deterioration",
            },
        ]
    )

    labels = {row["symbol"]: row["quality_label"] for row in payload.rows}
    assert labels["AAPL"] == "excellent_entry_exit"
    assert labels["MSFT"] == "good_entry_poor_exit"
    assert labels["META"] == "bad_entry_or_no_edge"
    assert labels["NVDA"] == "missed_high_quality_opportunity"
    assert labels["TSLA"] == "useful_rejection"
    assert payload.summary["report_version"] == "decision_quality_review_v1"
    assert payload.summary["excellent_trades"] == 1
    assert payload.summary["missed_opportunities"] == 1
    assert payload.summary["bad_entries_or_no_edge"] == 1
    assert payload.summary["poor_exit_after_good_entry"] == 1
    action_counts = {
        item["bucket"]: item["count"] for item in payload.learning_action_counts
    }
    assert action_counts["reduce_false_negative_gate_or_entry_timing"] == 1
    assert action_counts["tighten_peak_lock_or_exit_timing"] == 1
    assert action_counts["improve_entry_filter_or_timing"] == 1


def test_decision_quality_review_flags_missing_counterfactuals():
    payload = build_decision_quality_review_payload(
        [
            {
                "decision_time": "2026-06-03T10:30:00-04:00",
                "symbol": "NVDA",
                "approved": 0,
                "final_decision": "rejected",
                "rejection_reason": "trend_confirmation",
            },
        ]
    )

    assert payload.summary["missing_outcome_rows"] == 1
    assert payload.summary["analysis_ready"] is False
    assert payload.rows[0]["quality_label"] == "rejected_missing_forward_outcome"


def test_decision_quality_review_separates_exit_hold_observations():
    payload = build_decision_quality_review_payload(
        [
            {
                "decision_time": "2026-06-03T10:30:00-04:00",
                "symbol": "AAPL",
                "action": "sell",
                "approved": 0,
                "final_decision": "no_replace_now",
                "rejection_reason": "recommendation=observe_only",
            },
        ]
    )

    assert payload.summary["missing_outcome_rows"] == 0
    assert payload.summary["exit_hold_outcome_gaps"] == 1
    assert payload.rows[0]["quality_label"] == "exit_hold_observation"
    assert payload.rows[0]["learning_actions"] == ["add_exit_hold_forward_outcomes"]


def main():
    tests = [
        test_decision_quality_review_grades_entries_exits_and_misses,
        test_decision_quality_review_flags_missing_counterfactuals,
        test_decision_quality_review_separates_exit_hold_observations,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} decision quality review tests passed.")


if __name__ == "__main__":
    main()
