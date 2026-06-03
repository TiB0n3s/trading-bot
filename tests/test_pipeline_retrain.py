#!/usr/bin/env python3
"""Tests for automated retraining operational guardrails."""

from __future__ import annotations

from argparse import Namespace
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import retrain


def test_retrain_lock_reports_busy_when_already_held():
    with tempfile.TemporaryDirectory() as tmp:
        lock_file = str(Path(tmp) / "retrain.lock")
        with retrain._nonblocking_lock(lock_file) as first_acquired:
            assert first_acquired is True
            with retrain._nonblocking_lock(lock_file) as second_acquired:
                assert second_acquired is False


def test_main_returns_timeout_status_without_live_authority():
    original_parse = retrain._parse_args
    original_execute = retrain._execute_retraining

    def fake_parse():
        return Namespace(
            lock_file="",
            max_runtime_seconds=0,
            json=True,
        )

    def fake_execute(args):  # noqa: ARG001
        raise retrain.RetrainingTimeout("test timeout")

    try:
        retrain._parse_args = fake_parse
        retrain._execute_retraining = fake_execute
        assert retrain.main() == 124
    finally:
        retrain._parse_args = original_parse
        retrain._execute_retraining = original_execute


def test_execute_retraining_skips_completed_target_date():
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp) / "artifacts"
        marker_dir = artifact_dir / "retrain_runs"
        marker_dir.mkdir(parents=True)
        marker = marker_dir / "2026-06-03.json"
        marker.write_text(json.dumps({
            "status": "trained_without_registry_promotion",
            "target_date": "2026-06-03",
            "model_id": "existing",
        }))
        args = Namespace(
            artifact_dir=str(artifact_dir),
            target_date="2026-06-03",
            end_date=None,
            rerun_completed=False,
            json=True,
        )

        assert retrain._execute_retraining(args) == 0


def test_execute_retraining_writes_diagnostic_and_run_marker():
    original_drift = retrain.build_default_prediction_drift_service
    original_fetch = retrain.fetch_training_rows
    original_train = retrain.train_supervised_prediction_model

    class FakeReport:
        def to_dict(self):
            return {
                "average_correlation": -0.2,
                "bad_session_count": 3,
                "valid_session_count": 3,
                "retraining_recommended": True,
                "warning": True,
                "date_scores": [
                    {"market_date": "2026-06-03", "correlation": -0.2}
                ],
            }

    class FakeDrift:
        def correlation_report(self, **kwargs):  # noqa: ARG002
            return FakeReport()

    class FakeTraining:
        def to_dict(self):
            return {
                "trained": True,
                "artifact_path": str(artifact_path),
                "sample_size": 40,
                "provider": "fake",
                "accuracy": 0.55,
            }

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        sqlite3.connect(db_path).close()
        artifact_dir = Path(tmp) / "artifacts"
        artifact_path = artifact_dir / "candidate.joblib"

        def fake_train(**kwargs):  # noqa: ARG001
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(b"model")
            return FakeTraining()

        try:
            retrain.build_default_prediction_drift_service = lambda db_path=None: FakeDrift()
            retrain.fetch_training_rows = lambda **kwargs: [{} for _ in range(40)]
            retrain.train_supervised_prediction_model = fake_train
            args = Namespace(
                artifact_dir=str(artifact_dir),
                target_date="2026-06-03",
                end_date=None,
                rerun_completed=False,
                memory_limit_mb=0,
                nice_increment=0,
                db_path=str(db_path),
                sessions=5,
                threshold=0.0,
                bad_session_limit=3,
                min_pairs=3,
                force=False,
                limit=40,
                horizon="15m",
                min_samples=40,
                start_date=None,
                trading_sessions_observed=0,
                requested_status="candidate",
                operator_approved=False,
                json=True,
            )

            assert retrain._execute_retraining(args) == 0
        finally:
            retrain.build_default_prediction_drift_service = original_drift
            retrain.fetch_training_rows = original_fetch
            retrain.train_supervised_prediction_model = original_train

        markers = list((artifact_dir / "retrain_runs").glob("2026-06-03.json"))
        diagnostics = list(artifact_dir.glob("*.diagnostic.json"))
        assert markers, "expected completed run marker"
        assert diagnostics, "expected diagnostic companion JSON"
        diagnostic = json.loads(diagnostics[0].read_text())
        assert diagnostic["training_sample_size"] == 40
        assert diagnostic["validation_average_correlation"] == -0.2
        assert "python_version" in diagnostic


def main():
    tests = [
        test_retrain_lock_reports_busy_when_already_held,
        test_main_returns_timeout_status_without_live_authority,
        test_execute_retraining_skips_completed_target_date,
        test_execute_retraining_writes_diagnostic_and_run_marker,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} pipeline retrain tests passed.")


if __name__ == "__main__":
    main()
