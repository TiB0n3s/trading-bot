#!/usr/bin/env python3
"""Tests for observe-only AI review suite helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ai_review_suite_service import (  # noqa: E402
    AI_REVIEW_RUNTIME_EFFECT,
    build_ai_review_suite,
    candidate_universe_reviewer,
    daily_operator_briefing,
    exit_pattern_interpreter,
    feature_overlap_detector,
    lifecycle_trade_reviewer,
    model_readiness_reviewer,
    policy_disagreement_explainer,
    remediation_task_generator,
    setup_structure_explainer,
    source_evidence_auditor,
)


def _assert_review_only(payload):
    assert payload["runtime_effect"] == AI_REVIEW_RUNTIME_EFFECT
    assert payload["authority"] == "review_only_no_trade_authority"
    assert payload["decision_effect"] == "none"
    assert payload["schema_version"] == "ai_review_suite_v1"


def test_policy_disagreement_explainer_flags_mixed_authority_state():
    payload = policy_disagreement_explainer(
        advisory_authority_state={
            "decision_policy_outcome": {"advisory_decision": "allow"},
            "ml_outcome": {"advisory_decision": "avoid"},
        },
        approved=True,
    )
    _assert_review_only(payload)
    assert payload["conflict_detected"] is True
    assert "ml" in payload["negative_sources"]


def test_lifecycle_trade_reviewer_labels_missed_rejection():
    payload = lifecycle_trade_reviewer(
        {
            "approved": False,
            "lifecycle_status": "rejected_with_counterfactual",
            "rejected_max_favorable_60m": 1.2,
        }
    )
    _assert_review_only(payload)
    assert payload["review_label"] == "rejected_missed_opportunity"


def test_candidate_universe_reviewer_counts_candidates():
    payload = candidate_universe_reviewer(
        [
            {"near_threshold": True, "decision": "skip", "mfe_pct": 1.4},
            {"near_threshold": False, "decision": "approved", "mfe_pct": 0.1},
        ]
    )
    _assert_review_only(payload)
    assert payload["candidate_count"] == 2
    assert payload["near_threshold_count"] == 1
    assert payload["later_good_count"] == 1


def test_source_evidence_auditor_flags_unsupported_bullish_inference():
    payload = source_evidence_auditor(
        {
            "source_tier": "unclassified",
            "expected_market_impact": "moderately_bullish",
            "confirmation_status": "unconfirmed",
        }
    )
    _assert_review_only(payload)
    assert payload["audit_result"] == "needs_review"


def test_daily_operator_briefing_and_remediation_tasks():
    inputs = {
        "runtime_health": {"ok": False},
        "context_freshness": {"stale_count": 2},
    }
    briefing = daily_operator_briefing(inputs)
    tasks = remediation_task_generator(inputs)
    _assert_review_only(briefing)
    _assert_review_only(tasks)
    assert briefing["briefing_label"] == "attention_required"
    assert tasks["task_count"] >= 2


def test_exit_pattern_and_feature_overlap_and_model_readiness_and_setup():
    exit_payload = exit_pattern_interpreter({"missed_upside_pct": 1.5})
    overlap = feature_overlap_detector(
        [
            {"feature_family": "market_regime"},
            {"feature_family": "regime_participation"},
        ]
    )
    readiness = model_readiness_reviewer(
        {"status": "size_down_candidate", "failed_thresholds": []}
    )
    setup = setup_structure_explainer(
        {
            "quality_recommendation": "favorable",
            "structure_state": "high_quality_structure",
            "failed_breakout_risk": "low",
        }
    )
    for payload in (exit_payload, overlap, readiness, setup):
        _assert_review_only(payload)
    assert exit_payload["review_label"] == "potentially_early_exit"
    assert overlap["overlap_risk"] == "elevated"
    assert readiness["review_label"] == "promotion_candidate"
    assert setup["review_label"] == "clean_setup"


def test_build_ai_review_suite_contains_all_ten_sections():
    payload = build_ai_review_suite(
        symbol="AAPL",
        canonical={
            "advisory_authority_state": {
                "decision_policy_outcome": {"advisory_decision": "allow"},
                "ml_outcome": {"advisory_decision": "avoid"},
            },
            "setup_state": {"quality_recommendation": "favorable"},
        },
        lifecycle_row={"approved": True, "realized_return_pct": 0.3},
        candidates=[{"near_threshold": True}],
        event={"source_tier": "official", "confirmation_status": "official_confirmed"},
        ops_inputs={"runtime_health": {"ok": True}},
        feature_families=[{"feature_family": "execution_quality"}],
        rollout_assessment={"status": "observe_only"},
    )
    assert payload["runtime_effect"] == AI_REVIEW_RUNTIME_EFFECT
    assert payload["authority"] == "review_only_no_trade_authority"
    assert payload["decision_effect"] == "none"
    assert payload["schema_version"] == "ai_review_suite_v1"
    for key in (
        "policy_disagreement",
        "lifecycle_trade_review",
        "candidate_universe_review",
        "source_evidence_audit",
        "daily_operator_briefing",
        "exit_pattern",
        "feature_overlap",
        "model_readiness",
        "setup_structure",
        "remediation_tasks",
    ):
        assert key in payload


def main():
    tests = [
        test_policy_disagreement_explainer_flags_mixed_authority_state,
        test_lifecycle_trade_reviewer_labels_missed_rejection,
        test_candidate_universe_reviewer_counts_candidates,
        test_source_evidence_auditor_flags_unsupported_bullish_inference,
        test_daily_operator_briefing_and_remediation_tasks,
        test_exit_pattern_and_feature_overlap_and_model_readiness_and_setup,
        test_build_ai_review_suite_contains_all_ten_sections,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} AI review suite tests passed.")


if __name__ == "__main__":
    main()
