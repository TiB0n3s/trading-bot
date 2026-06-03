#!/usr/bin/env python3
"""Tests for conservative ML promotion gate."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_platform.promotion import assess_candidate_promotion, register_candidate_model


def _readiness(blockers=None):
    return {"current_evidence": {"blockers": list(blockers or [])}}


def _validation(avg=0.25, warning=False, sessions=3):
    return {
        "average_correlation": avg,
        "warning": warning,
        "retraining_recommended": warning,
        "date_scores": [
            {
                "market_date": f"2026-06-0{i + 1}",
                "pair_count": 5,
                "correlation": avg,
                "status": "directional" if avg > 0 else "flat_or_negative",
            }
            for i in range(sessions)
        ],
    }


def test_readiness_blockers_prevent_candidate_registration():
    assessment = assess_candidate_promotion(
        readiness_report=_readiness(["missing_matched_trade_outcomes"]),
        validation_report=_validation(),
        requested_status="candidate",
    )

    assert assessment.allowed is False
    assert "readiness:missing_matched_trade_outcomes" in assessment.blockers


def test_directional_validation_allows_candidate_metadata():
    assessment = assess_candidate_promotion(
        readiness_report=_readiness(),
        validation_report=_validation(avg=0.31),
        requested_status="candidate",
    )

    assert assessment.allowed is True
    assert assessment.status_to_register == "candidate"
    assert assessment.runtime_effect == "metadata_only_no_live_authority"


def test_promotion_beyond_warn_only_requires_explicit_operator_approval():
    assessment = assess_candidate_promotion(
        readiness_report=_readiness(),
        validation_report=_validation(avg=0.31),
        requested_status="paper_gate",
    )

    assert assessment.allowed is False
    assert "promotion:operator_approval_required_beyond_warn_only" in assessment.blockers


def test_register_candidate_model_writes_registry_metadata_only():
    assessment = assess_candidate_promotion(
        readiness_report=_readiness(),
        validation_report=_validation(avg=0.31),
        requested_status="candidate",
    )
    with tempfile.TemporaryDirectory() as tmp:
        registry_path = Path(tmp) / "registry.json"
        entry = register_candidate_model(
            assessment=assessment,
            model_id="candidate_v1",
            artifact_path="/tmp/candidate.joblib",
            metrics_path="/tmp/candidate.metrics.json",
            feature_version="feature_v1",
            target="ret_fwd_15m",
            training_window="2026-05-01..2026-06-01",
            validation_window="last_3_prediction_sessions",
            registry_path=registry_path,
        )
        registry = json.loads(registry_path.read_text())

    assert entry["status"] == "candidate"
    assert entry["runtime_use"] == "requires_explicit_review"
    assert registry["models"][0]["model_id"] == "candidate_v1"


def main():
    tests = [
        test_readiness_blockers_prevent_candidate_registration,
        test_directional_validation_allows_candidate_metadata,
        test_promotion_beyond_warn_only_requires_explicit_operator_approval,
        test_register_candidate_model_writes_registry_metadata_only,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ML promotion tests passed.")


if __name__ == "__main__":
    main()
