#!/usr/bin/env python3
"""Tests for PSI concept-drift governance."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

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


def main():
    tests = [
        test_population_stability_index_identifies_shift,
        test_concept_drift_service_writes_severe_artifact,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} concept drift tests passed.")


if __name__ == "__main__":
    main()
