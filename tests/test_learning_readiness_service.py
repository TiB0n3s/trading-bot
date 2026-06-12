"""Tests for holistic learning readiness summaries."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.learning_readiness_service import build_learning_readiness_payload  # noqa: E402


def _base_payload(**overrides):
    kwargs = {
        "start_date": "2026-06-09",
        "end_date": "2026-06-09",
        "lifecycle_summary": {
            "rows": 1,
            "approved_with_exit": 0,
            "approved_matched_exit_missing_snapshot": 1,
            "approved_open_or_unlinked_exit": 0,
            "approved_exit_link_rate": 0.0,
            "approved_matched_exit_coverage_rate": 1.0,
            "rejected_with_counterfactual": 0,
            "rejected_without_counterfactual": 0,
            "analysis_ready": True,
        },
        "lifecycle_rows": [
            {
                "decision_time": "2026-06-09T10:00:00+00:00",
                "approved": 1,
                "realized_return_pct": 0.4,
                "canonical_intelligence_json": '{"setup_label":"breakout","model_probability":0.72}',
                "symbol_pattern": "trend_continuation",
                "momentum_score": 2.0,
                "prediction_score": 0.72,
                "decision_policy_outcome": "allowed",
            }
        ],
        "runtime_trend": {
            "rows": 2,
            "jobs": [],
            "clean": True,
        },
        "candidate_rows": [
            {
                "candidate_ts": "2026-06-09T10:00:00+00:00",
                "symbol": "AAPL",
                "candidate_status": "taken",
                "candidate_kind": "entry",
                "score": 70,
                "candidate_json": '{"forward_return_pct":0.4}',
            }
        ],
        "symbol_pattern_summary": {"pattern_rows": 1, "rows_with_outcome": 1},
        "feature_summary": {},
        "feature_guardrails": [],
        "calibration_summary": {"ready_bucket_count": 1},
        "strategy_memory": {
            "generated_at": "2026-06-09T22:00:00+00:00",
            "trade_count": 1,
            "setup_label_context": {"breakout": {"recommendation": "prefer"}},
        },
        "full_readiness_target": 1,
    }
    kwargs.update(overrides)
    return build_learning_readiness_payload(**kwargs)


def test_matched_approved_exits_clear_hard_exit_outcome_blocker():
    payload = _base_payload()

    assert "approved_exit_outcome_coverage_below_80pct" not in payload.blockers
    assert "approved_exit_link_rate_below_80pct" not in payload.blockers
    assert payload.lifecycle["approved_exit_link_rate"] == 0.0
    assert payload.lifecycle["approved_matched_exit_coverage_rate"] == 1.0
    assert payload.lifecycle["approved_exit_outcome_coverage_rate"] == 1.0
    assert any("repair canonical exit snapshot" in item for item in payload.next_actions)


def test_learning_readiness_accepts_precomputed_candidate_summary():
    payload = _base_payload(
        candidate_rows=[],
        candidate_summary={
            "rows": 2,
            "scored_rows": 2,
            "near_threshold": 1,
            "scored_not_taken": 0,
            "taken": 1,
            "exit_considered_not_taken": 0,
            "by_status": {"near_threshold": 1, "taken": 1},
            "by_kind": {"entry": 2},
            "rows_with_forward_outcome": 2,
            "missing_forward_outcome": 0,
            "forward_outcome_coverage_rate": 1.0,
            "non_taken_rows": 1,
            "non_taken_with_forward_outcome": 1,
            "non_taken_forward_outcome_coverage_rate": 1.0,
        },
    )

    assert payload.candidate_universe["rows"] == 2
    assert payload.candidate_universe["forward_outcome_coverage_rate"] == 1.0
    assert "candidate_forward_outcome_coverage_below_80pct" not in payload.blockers


if __name__ == "__main__":
    test_matched_approved_exits_clear_hard_exit_outcome_blocker()
    test_learning_readiness_accepts_precomputed_candidate_summary()
    print("learning readiness service tests passed")
