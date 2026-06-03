#!/usr/bin/env python3
"""Tests for ML advisory/authority promotion boundaries."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.approval_service import evaluate_ml_authority_outcome


def _gate(**overrides):
    gate = {
        "ml_prediction_compare_decision": "avoid",
        "ml_prediction_sample_size": 30,
        "ml_prediction_confidence": "medium",
    }
    gate.update(overrides)
    return gate


def _config(**overrides):
    config = {
        "authority_mode": "observe_only_compare",
        "min_sample_size": 20,
        "min_confidence": "medium",
        "max_age_seconds": 0,
        "size_cap_pct": 0.8,
        "negative_decisions": ["avoid", "block", "caution"],
    }
    config.update(overrides)
    return config


def test_observe_mode_records_negative_compare_without_enforcement():
    outcome = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={},
        ml_authority_config=_config(authority_mode="observe_only_compare"),
        execution_mode="paper",
    )

    assert outcome.negative_compare is True
    assert outcome.qualified_for_authority is True
    assert outcome.enforced is False
    assert outcome.effect_on_execution == "none"
    assert outcome.would_block_under_promoted_mode is True
    assert "ignored by design" in outcome.reason


def test_size_down_mode_enforces_size_cap_only():
    outcome = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={},
        ml_authority_config=_config(authority_mode="size_down_only", size_cap_pct=0.65),
        execution_mode="cash_full",
    )

    assert outcome.enforced is True
    assert outcome.effect_on_size == "cap"
    assert outcome.effect_on_execution == "none"
    assert outcome.size_cap_pct == 0.65


def test_paper_block_mode_only_blocks_paper_execution_modes():
    paper = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={},
        ml_authority_config=_config(authority_mode="paper_block"),
        execution_mode="paper",
    )
    live = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={},
        ml_authority_config=_config(authority_mode="paper_block"),
        execution_mode="cash_full",
    )

    assert paper.enforced is True
    assert paper.effect_on_execution == "block"
    assert live.enforced is False
    assert live.effect_on_execution == "none"


def test_authority_requires_sample_confidence_and_optional_recency():
    low_sample = evaluate_ml_authority_outcome(
        prediction_gate=_gate(ml_prediction_sample_size=3),
        ml_prediction={},
        ml_authority_config=_config(authority_mode="live_block"),
        execution_mode="cash_full",
    )
    low_confidence = evaluate_ml_authority_outcome(
        prediction_gate=_gate(ml_prediction_confidence="low"),
        ml_prediction={},
        ml_authority_config=_config(authority_mode="live_block"),
        execution_mode="cash_full",
    )
    stale = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={"prediction_generated_at": "2020-01-01T00:00:00+00:00"},
        ml_authority_config=_config(authority_mode="live_block", max_age_seconds=60),
        execution_mode="cash_full",
    )

    assert low_sample.qualified_for_authority is False
    assert low_sample.enforced is False
    assert low_confidence.qualified_for_authority is False
    assert low_confidence.enforced is False
    assert stale.qualified_for_authority is False
    assert stale.enforced is False


def test_live_block_requires_safe_runtime_and_freshness_config():
    unsafe = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={},
        ml_authority_config=_config(authority_mode="live_block", max_age_seconds=0),
        execution_mode="paper",
    )
    safe = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={"prediction_generated_at": "2999-01-01T00:00:00+00:00"},
        ml_authority_config=_config(authority_mode="live_block", max_age_seconds=3600),
        execution_mode="cash_full",
    )

    assert unsafe.qualified_for_authority is True
    assert unsafe.enforced is False
    assert unsafe.safety_check_passed is False
    assert any("not live-compatible" in blocker for blocker in unsafe.safety_blockers)
    assert any("max_age_seconds" in blocker for blocker in unsafe.safety_blockers)
    assert any("freshness timestamp missing" in blocker for blocker in unsafe.safety_blockers)
    assert safe.enforced is True
    assert safe.effect_on_execution == "block"


def test_recency_uses_only_canonical_prediction_generated_at():
    legacy_only = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={"generated_at": "2999-01-01T00:00:00+00:00"},
        ml_authority_config=_config(authority_mode="live_block", max_age_seconds=3600),
        execution_mode="cash_full",
    )

    assert legacy_only.qualified_for_authority is False
    assert legacy_only.enforced is False
    assert any("freshness timestamp missing" in blocker for blocker in legacy_only.safety_blockers)


def test_recency_handles_naive_and_timezone_aware_canonical_timestamps():
    aware_fresh = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    naive_fresh = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30)
    ).isoformat()

    aware = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={"prediction_generated_at": aware_fresh},
        ml_authority_config=_config(authority_mode="live_block", max_age_seconds=3600),
        execution_mode="cash_full",
    )
    naive = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={"prediction_generated_at": naive_fresh},
        ml_authority_config=_config(authority_mode="live_block", max_age_seconds=3600),
        execution_mode="cash_full",
    )

    assert aware.enforced is True
    assert aware.prediction_age_seconds is not None
    assert naive.enforced is True
    assert naive.prediction_age_seconds is not None


def test_stale_model_guard_disables_all_ml_authority_effects():
    outcome = evaluate_ml_authority_outcome(
        prediction_gate=_gate(),
        ml_prediction={"prediction_generated_at": "2999-01-01T00:00:00+00:00"},
        ml_authority_config=_config(
            authority_mode="size_down_only",
            model_staleness_guard={
                "fallback_required": True,
                "reason": "configured model is stale",
            },
        ),
        execution_mode="cash_full",
    )

    assert outcome.qualified_for_authority is False
    assert outcome.enforced is False
    assert outcome.effect_on_size == "none"
    assert "deterministic fallback" in outcome.reason


def main():
    tests = [
        test_observe_mode_records_negative_compare_without_enforcement,
        test_size_down_mode_enforces_size_cap_only,
        test_paper_block_mode_only_blocks_paper_execution_modes,
        test_authority_requires_sample_confidence_and_optional_recency,
        test_live_block_requires_safe_runtime_and_freshness_config,
        test_recency_uses_only_canonical_prediction_generated_at,
        test_recency_handles_naive_and_timezone_aware_canonical_timestamps,
        test_stale_model_guard_disables_all_ml_authority_effects,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ML authority tests passed.")


if __name__ == "__main__":
    main()
