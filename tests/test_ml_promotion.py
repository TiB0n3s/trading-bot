#!/usr/bin/env python3
"""Tests for conservative ML promotion gate."""
# ruff: noqa: E402

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_platform.promotion import assess_candidate_promotion, register_candidate_model
from ml_platform.registry import model_staleness_guard, prune_model_artifacts


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


def test_simple_split_validation_blocks_promotion_gate():
    report = _validation(avg=0.31)
    report["validation_method"] = "chronological_80_20_observe_only"
    assessment = assess_candidate_promotion(
        readiness_report=_readiness(),
        validation_report=report,
        requested_status="candidate",
    )

    assert assessment.allowed is False
    assert "validation:simple_split_not_promotion_eligible" in assessment.blockers


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


def test_model_staleness_guard_requires_fallback_for_old_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact = root / "candidate.joblib"
        artifact.write_bytes(b"model")
        registry_path = root / "registry.json"
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        registry_path.write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "model_id": "candidate_v1",
                            "artifact_path": str(artifact),
                            "created_at": old,
                            "updated_at": old,
                        }
                    ]
                }
            )
        )
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
        artifact.touch()
        os.utime(artifact, (old_ts, old_ts))

        guard = model_staleness_guard(
            model_id="candidate_v1",
            max_age_seconds=60,
            registry_path=registry_path,
        )

    assert guard["fallback_required"] is True
    assert guard["status"] == "stale"
    assert guard["fallback_strategy"] == "deterministic_policy_no_ml_authority"


def test_prune_model_artifacts_preserves_candidate_and_diagnostics():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_delete = root / "old_delete.joblib"
        old_candidate = root / "old_candidate.joblib"
        recent_fallback = root / "recent_fallback.joblib"
        for artifact in (old_delete, old_candidate, recent_fallback):
            artifact.write_text("model")
            artifact.with_suffix(artifact.suffix + ".diagnostic.json").write_text("{}")
        old_ts = time.time() - 40 * 86400
        os.utime(old_delete, (old_ts, old_ts))
        os.utime(old_candidate, (old_ts, old_ts))
        registry_path = root / "registry.json"
        registry_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "models": [
                        {
                            "model_id": "delete-me",
                            "status": "retired",
                            "artifact_path": str(old_delete),
                            "created_at": "2026-01-01T00:00:00+00:00",
                        },
                        {
                            "model_id": "candidate",
                            "status": "candidate",
                            "artifact_path": str(old_candidate),
                            "created_at": "2026-01-02T00:00:00+00:00",
                        },
                        {
                            "model_id": "fallback",
                            "status": "retired",
                            "artifact_path": str(recent_fallback),
                            "created_at": "2026-06-01T00:00:00+00:00",
                        },
                    ],
                }
            )
        )

        report = prune_model_artifacts(
            registry_path=registry_path,
            older_than_days=30,
            fallback_count=1,
            now=datetime.now(timezone.utc),
        )

        assert report["deleted_count"] == 1
        assert not old_delete.exists()
        assert old_delete.with_suffix(old_delete.suffix + ".diagnostic.json").exists()
        assert old_candidate.exists()
        assert recent_fallback.exists()


def main():
    tests = [
        test_readiness_blockers_prevent_candidate_registration,
        test_directional_validation_allows_candidate_metadata,
        test_simple_split_validation_blocks_promotion_gate,
        test_promotion_beyond_warn_only_requires_explicit_operator_approval,
        test_register_candidate_model_writes_registry_metadata_only,
        test_model_staleness_guard_requires_fallback_for_old_artifact,
        test_prune_model_artifacts_preserves_candidate_and_diagnostics,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ML promotion tests passed.")


if __name__ == "__main__":
    main()
