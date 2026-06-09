#!/usr/bin/env python3
"""Tests for PSI concept-drift governance."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from db import get_connection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.concept_drift_service import (  # noqa: E402
    ConceptDriftService,
    population_stability_index,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value, got {value!r}")


class FakeRepo:
    def feature_values(self, *, feature, start_date, end_date, **_kwargs):
        if feature == "vpin_toxicity_20":
            if start_date == "2024-06-01":
                return [0.05 + (i % 10) * 0.01 for i in range(200)]
            return [0.75 + (i % 10) * 0.01 for i in range(50)]
        if start_date == "2024-06-01":
            return [1.0 + (i % 10) * 0.01 for i in range(200)]
        return [1.0 + (i % 10) * 0.01 for i in range(50)]


class FakeArchiveRepo(FakeRepo):
    def __init__(self):
        self.archived_reports = []

    def archive_drift_regime(self, report):
        self.archived_reports.append(report)
        return 7


def test_population_stability_index_identifies_shift():
    stable = population_stability_index(
        [1.0 + (i % 10) * 0.01 for i in range(200)],
        [1.0 + (i % 10) * 0.01 for i in range(50)],
    )
    shifted = population_stability_index(
        [1.0 + (i % 10) * 0.01 for i in range(200)],
        [2.0 + (i % 10) * 0.01 for i in range(50)],
    )
    assert_true(stable is not None and stable < 0.10, "stable PSI")
    assert_true(shifted is not None and shifted > 0.25, "shifted PSI")


def test_concept_drift_service_writes_severe_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "concept_drift.json"
        report = (
            ConceptDriftService(repository=FakeRepo())
            .psi_report(
                target_date="2026-06-09",
                baseline_start="2024-06-01",
                features=("vpin_toxicity_20", "range_atr_ratio"),
                artifact_path=artifact,
            )
            .to_dict()
        )

        assert_equal(report["severe_drift"], True, "severe drift")
        assert_equal(
            report["action"],
            "disable_counterfactual_veto_relaxation_until_retraining",
            "action",
        )
        assert_true(artifact.exists(), "artifact written")


def test_concept_drift_service_archives_severe_regime_window():
    from repositories.concept_drift_repo import ConceptDriftRepository

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "drift.db"
        repo = ConceptDriftRepository(db_path=db_path)
        service = ConceptDriftService(repository=repo)
        artifact = Path(tmp) / "concept_drift.json"

        report = service.psi_report(
            target_date="2026-06-09",
            baseline_start="2024-06-01",
            features=("vpin_toxicity_20",),
            artifact_path=artifact,
        ).to_dict()

        assert_equal(report["severe_drift"], False, "empty db is not severe")

        # Use fake severe values through the repository archive method to validate
        # the canonical persistence path without building a full bar feature table.
        archive_id = repo.archive_drift_regime(
            {
                "target_date": "2026-06-09",
                "baseline_window": {"start": "2024-06-01", "end": "2026-06-09"},
                "recent_window": {"start": "2026-06-05", "end": "2026-06-09"},
                "severe_psi_threshold": 0.25,
                "max_psi": 0.52,
                "severe_drift": True,
                "features": [{"feature": "vpin_toxicity_20", "psi": 0.52}],
                "generated_at": "2026-06-09T14:00:00+00:00",
            }
        )
        assert_true(archive_id > 0, "archive id")
        with get_connection(db_path) as con:
            row = con.execute(
                "SELECT target_date, max_psi, severe_drift FROM drift_regime_archives"
            ).fetchone()
        assert_equal(row["target_date"], "2026-06-09", "target date")
        assert_equal(row["severe_drift"], 1, "severe flag")


def test_concept_drift_service_calls_archive_hook_on_severe_drift():
    repo = FakeArchiveRepo()
    report = (
        ConceptDriftService(repository=repo)
        .psi_report(
            target_date="2026-06-09",
            baseline_start="2024-06-01",
            features=("vpin_toxicity_20",),
            artifact_path=None,
        )
        .to_dict()
    )

    assert_equal(report["severe_drift"], True, "severe drift")
    assert_equal(report["drift_regime_archive_id"], 7, "archive id")
    assert_equal(len(repo.archived_reports), 1, "archive call")


def main():
    tests = [
        test_population_stability_index_identifies_shift,
        test_concept_drift_service_writes_severe_artifact,
        test_concept_drift_service_archives_severe_regime_window,
        test_concept_drift_service_calls_archive_hook_on_severe_drift,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} concept drift tests passed.")


if __name__ == "__main__":
    main()
