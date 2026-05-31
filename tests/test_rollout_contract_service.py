#!/usr/bin/env python3
"""Tests for rollout contract governance."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.rollout_contract_service import (
    ROLLOUT_CONTRACT_VERSION,
    RolloutStatus,
    RolloutThresholds,
    assess_all_feature_family_rollouts,
    assess_feature_family_rollout,
    telemetry_only_rollout_contract,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def _family(
    name,
    *,
    covered=200,
    missing=0.02,
    stability=0.70,
    fp=0.04,
    fn=0.05,
):
    return {
        "family": name,
        "covered_rows": covered,
        "missing_rate": missing,
        "stability": {"stable_window_share": stability, "window_count": 4},
        "best_bucket": {
            "bucket": "bad_state",
            "interactions": {
                "setup_label": [{"bucket": "late_chase", "count": 10}],
                "regime": [{"bucket": "compression_chop", "count": 10}],
                "session_phase": [{"bucket": "midday", "count": 10}],
            },
        },
        "worst_bucket": {"bucket": "good_state"},
        "buckets": [
            {
                "bucket": "bad_state",
                "sample_size": covered,
                "false_positive_reduction": fp,
                "false_negative_increase": fn,
            }
        ],
    }


def _thresholds():
    return RolloutThresholds(
        min_sample_size_size_down=100,
        min_sample_size_block=180,
        max_missing_rate=0.10,
        min_stability_share_size_down=0.60,
        min_stability_share_block=0.75,
        max_overlap_risk_for_promotion=0.50,
        max_false_negative_cost_size_down=0.15,
        max_false_negative_cost_block=0.10,
        min_false_positive_reduction_size_down=0.03,
        min_false_positive_reduction_block=0.05,
        max_status_by_family={
            "portfolio_decision": RolloutStatus.NARROW_BLOCK_CANDIDATE,
            "execution_quality": RolloutStatus.NARROW_BLOCK_CANDIDATE,
            "market_regime": RolloutStatus.SIZE_DOWN_CANDIDATE,
        },
    )


def test_not_ready_on_hard_guardrail_failure():
    assessment = assess_feature_family_rollout(
        family_payload=_family("market_regime", covered=20),
        calibration_quality="high",
        thresholds=_thresholds(),
    )

    assert_equal(assessment.status, RolloutStatus.NOT_READY, "status")
    assert_true("sample_size_below_size_down_minimum" in assessment.guardrail_failures, "sample failure")


def test_size_down_candidate_requires_evidence_and_calibration():
    assessment = assess_feature_family_rollout(
        family_payload=_family("market_regime"),
        calibration_quality="medium",
        thresholds=_thresholds(),
    )

    assert_equal(assessment.status, RolloutStatus.SIZE_DOWN_CANDIDATE, "status")
    assert_equal(assessment.restrictions["allowed_actions"], ["size_down_only"], "actions")
    assert_true("block_candidacy_not_allowlisted" in assessment.promotion_reasons, "block capped")


def test_narrow_block_candidate_requires_allowlist_and_stronger_thresholds():
    assessment = assess_feature_family_rollout(
        family_payload=_family(
            "portfolio_decision",
            covered=240,
            stability=0.80,
            fp=0.07,
            fn=0.04,
        ),
        calibration_quality="high",
        thresholds=_thresholds(),
    )

    assert_equal(assessment.status, RolloutStatus.NARROW_BLOCK_CANDIDATE, "status")
    assert_equal(
        assessment.restrictions["allowed_actions"],
        ["narrow_block_candidate_review_only"],
        "actions",
    )
    assert_equal(assessment.restrictions["global_block_allowed"], False, "no global block")
    assert_true(assessment.restrictions["setup_scope"], "setup scope")


def test_calibration_caps_to_observe_only():
    assessment = assess_feature_family_rollout(
        family_payload=_family("execution_quality", covered=240, stability=0.80, fp=0.07),
        calibration_quality="thin_sample",
        thresholds=_thresholds(),
    )

    assert_equal(assessment.status, RolloutStatus.OBSERVE_ONLY, "status")
    assert_true("calibration_quality_below_threshold" in assessment.guardrail_failures, "calibration cap")


def test_overlap_caps_promotion():
    assessment = assess_feature_family_rollout(
        family_payload=_family("execution_quality", covered=240, stability=0.80, fp=0.07),
        feature_overlap=[
            {
                "left_family": "execution_quality",
                "right_family": "market_microstructure",
                "overlap_rate": 0.62,
            }
        ],
        calibration_quality="high",
        thresholds=_thresholds(),
    )

    assert_equal(assessment.status, RolloutStatus.OBSERVE_ONLY, "status")
    assert_true("overlap_risk_caps_promotion" in assessment.guardrail_failures, "overlap cap")


def test_assess_all_payload_is_versioned_and_deterministic():
    payload = assess_all_feature_family_rollouts(
        attribution_payload={
            "families": [_family("execution_quality")],
            "feature_overlap": [],
        },
        calibration_summary={"execution_quality": {"calibration_quality": "medium"}},
        decision_date="2026-05-30",
        thresholds=_thresholds(),
    )

    data = payload.to_dict()
    assert_equal(data["report_version"], ROLLOUT_CONTRACT_VERSION, "version")
    assert_equal(data["decision_date"], "2026-05-30", "date")
    assert_equal(data["assessments"][0]["feature_family"], "execution_quality", "family")


def test_default_initial_family_caps_match_rollout_ladder():
    regime = assess_feature_family_rollout(
        family_payload=_family("market_regime", covered=500, stability=0.9, fp=0.10, fn=0.01),
        calibration_quality="high",
    )
    execution = assess_feature_family_rollout(
        family_payload=_family("execution_quality", covered=500, stability=0.9, fp=0.10, fn=0.01),
        calibration_quality="high",
    )
    portfolio = assess_feature_family_rollout(
        family_payload=_family("portfolio_decision", covered=500, stability=0.9, fp=0.10, fn=0.01),
        calibration_quality="high",
    )
    setup = assess_feature_family_rollout(
        family_payload=_family("setup_structure", covered=500, stability=0.9, fp=0.10, fn=0.01),
        calibration_quality="high",
    )
    downside = assess_feature_family_rollout(
        family_payload=_family("downside_asymmetry", covered=500, stability=0.9, fp=0.10, fn=0.01),
        calibration_quality="high",
    )

    assert_equal(regime.status, RolloutStatus.OBSERVE_ONLY, "regime cap")
    assert_equal(execution.status, RolloutStatus.SIZE_DOWN_CANDIDATE, "execution cap")
    assert_equal(portfolio.status, RolloutStatus.NARROW_BLOCK_CANDIDATE, "portfolio block")
    assert_equal(setup.status, RolloutStatus.OBSERVE_ONLY, "setup structure initial cap")
    assert_equal(downside.status, RolloutStatus.SIZE_DOWN_CANDIDATE, "downside cap")
    assert_true(
        "family_initial_target_cap=observe_only" in regime.promotion_reasons,
        "regime cap reason",
    )
    assert_true(
        "block_candidacy_not_allowlisted" in execution.promotion_reasons,
        "execution block cap reason",
    )


def test_telemetry_only_contract_has_no_assessments():
    contract = telemetry_only_rollout_contract()

    assert_equal(contract["report_version"], ROLLOUT_CONTRACT_VERSION, "version")
    assert_equal(contract["runtime_effect"], "telemetry_only_no_live_authority", "effect")
    assert_equal(contract["assessments"], [], "assessments")


def main():
    tests = [
        test_not_ready_on_hard_guardrail_failure,
        test_size_down_candidate_requires_evidence_and_calibration,
        test_narrow_block_candidate_requires_allowlist_and_stronger_thresholds,
        test_calibration_caps_to_observe_only,
        test_overlap_caps_promotion,
        test_assess_all_payload_is_versioned_and_deterministic,
        test_default_initial_family_caps_match_rollout_ladder,
        test_telemetry_only_contract_has_no_assessments,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} rollout contract service tests passed.")


if __name__ == "__main__":
    main()
