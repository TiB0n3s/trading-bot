#!/usr/bin/env python3
"""Tests for active learning integration diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.active_learning_integration_service import (
    build_active_learning_integration_payload,
)


def test_active_learning_integration_detects_wired_learning_paths():
    candidate_payload = {
        "candidate": {
            "symbol_pattern": "trend_continuation_with_participation",
            "pattern_runtime_effect": "observe_only_no_live_authority",
            "ml_prediction_score": 57.0,
            "ml_prediction_bucket": "high_55_plus",
            "setup_label": "near_vwap_recovery",
            "setup_recommendation": "favorable",
        },
        "forward_return_pct": 0.6,
        "forward_mfe_pct": 1.0,
    }
    payload = build_active_learning_integration_payload(
        start_date="2026-06-03",
        end_date="2026-06-03",
        auto_buy_rows=[
            {
                "reason": "strategy_memory:caution:min_setup=60:trades=10; ml_prediction:high_55_plus",
                "hard_block_reason": "",
                "candidate_json": json.dumps(candidate_payload),
                "order_submitted": 1,
                "live_block_reason": None,
            },
            {
                "reason": "strategy_memory:caution:min_setup=60:trades=10; strategy_memory_caution_caps_at_watch",
                "hard_block_reason": "",
                "candidate_json": json.dumps(candidate_payload),
                "order_submitted": 0,
                "live_block_reason": "decision=watch",
            },
        ],
        lifecycle_rows=[
            {
                "approved": 1,
                "realized_return_pct": 0.4,
                "symbol_pattern": "trend_continuation_with_participation",
                "session_trend_label": "strong_uptrend",
                "prediction_score": 56,
                "canonical_intelligence_json": json.dumps(
                    {
                        "advisory_authority_state": {
                            "decision_policy_outcome": {
                                "advisory_decision": "size_down",
                                "enforced": True,
                            }
                        }
                    }
                ),
            }
        ],
        candidate_rows=[
            {
                "candidate_status": "near_threshold",
                "candidate_json": json.dumps(
                    {
                        "forward_return_pct": 0.3,
                        "forward_mfe_pct": 0.8,
                    }
                ),
            }
        ],
        strategy_memory={
            "generated_at": "2026-06-03T20:00:00Z",
            "trade_count": 10,
            "setup_label_context": {"near_vwap_recovery": {"recommendation": "caution"}},
        },
    )

    assert payload.summary["report_version"] == "active_learning_integration_v1"
    assert payload.summary["actively_learning"] is True
    assert payload.auto_buy_path["strategy_memory_rows"] == 2
    assert payload.auto_buy_path["strategy_memory_constrained_rows"] == 1
    assert payload.auto_buy_path["symbol_pattern_rows"] == 2
    assert payload.auto_buy_path["symbol_pattern_authority_rows"] == 0
    assert payload.lifecycle_path["rows_with_outcome"] == 1
    assert payload.candidate_universe["rows_with_forward_outcome"] == 1
    assert payload.blockers == []


def test_active_learning_integration_reports_missing_paths():
    payload = build_active_learning_integration_payload(
        start_date="2026-06-03",
        end_date="2026-06-03",
        auto_buy_rows=[],
        lifecycle_rows=[],
        candidate_rows=[],
        strategy_memory={},
    )

    assert payload.summary["actively_learning"] is False
    assert "no_auto_buy_audit_rows" in payload.blockers
    assert "strategy_memory_artifact_missing" in payload.blockers
    assert "no_lifecycle_outcomes_for_learning" in payload.blockers
    assert "candidate_universe_missing" in payload.blockers


def main():
    tests = [
        test_active_learning_integration_detects_wired_learning_paths,
        test_active_learning_integration_reports_missing_paths,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} active learning integration tests passed.")


if __name__ == "__main__":
    main()
