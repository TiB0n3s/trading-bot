#!/usr/bin/env python3
"""Tests for consolidated model validation governance diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_platform.lifecycle import REQUIRED_PROMOTION_METRICS  # noqa: E402
from services.model_validation_governance_service import (  # noqa: E402
    build_model_validation_governance_payload,
)


def _write_diag(
    candidate_dir: Path,
    *,
    label: str,
    accuracy: float | None = 0.76,
    rows_loaded: int = 6000,
    generated_at: str = "2026-06-08T12:00:00+00:00",
    trained: bool = True,
    validation_method: str = "purged_walk_forward_v1",
    include_metrics: bool = True,
) -> None:
    metrics = {key: 0.1 for key in REQUIRED_PROMOTION_METRICS} if include_metrics else {}
    payload = {
        "runtime_effect": "observe_only_no_live_authority",
        "model_id": f"historical_bar_{label}_{generated_at}",
        "label_target": label,
        "generated_at": generated_at,
        "rows_loaded": rows_loaded,
        "symbol_count": 59,
        "training": {
            "trained": trained,
            "accuracy": accuracy,
            "validation_method": validation_method,
            "promotion_metrics": metrics,
        },
    }
    safe_ts = generated_at.replace(":", "").replace("-", "")
    (candidate_dir / f"historical_bar_{label}_{safe_ts}.diagnostic.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_model_validation_governance_accepts_observe_only_candidates():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        candidate_dir = base / "candidates"
        evidence_dir = base / "evidence"
        candidate_dir.mkdir()
        evidence_dir.mkdir()
        registry_path = base / "registry.json"
        registry_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
        _write_diag(candidate_dir, label="triple_barrier_label")

        payload = build_model_validation_governance_payload(
            candidate_dir=candidate_dir,
            registry_path=registry_path,
            promotion_evidence_dir=evidence_dir,
            min_rows=5000,
            min_symbols=20,
            min_accuracy=0.50,
        )

    assert payload["ready_for_observe_only_validation"] is True
    assert payload["ready_for_live_promotion"] is False
    assert payload["blockers"] == []
    assert payload["ready_label_count"] == 1
    assert payload["ready_for_candidate_registration"] is True


def test_model_validation_governance_blocks_live_registry_status():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        candidate_dir = base / "candidates"
        candidate_dir.mkdir()
        registry_path = base / "registry.json"
        registry_path.write_text(
            json.dumps({"entries": {"model-a": {"status": "production"}}}),
            encoding="utf-8",
        )
        _write_diag(candidate_dir, label="triple_barrier_label")

        payload = build_model_validation_governance_payload(
            candidate_dir=candidate_dir,
            registry_path=registry_path,
            min_rows=5000,
            min_symbols=20,
            min_accuracy=0.50,
        )

    assert payload["ready_for_observe_only_validation"] is False
    assert "registry:live_authority_status_present" in payload["blockers"]
    assert payload["live_registry_entry_count"] == 1


def test_model_validation_governance_requires_promotion_evidence_for_live_readiness():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        candidate_dir = base / "candidates"
        evidence_dir = base / "evidence"
        candidate_dir.mkdir()
        evidence_dir.mkdir()
        registry_path = base / "registry.json"
        registry_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
        _write_diag(candidate_dir, label="triple_barrier_label")

        payload = build_model_validation_governance_payload(
            candidate_dir=candidate_dir,
            registry_path=registry_path,
            promotion_evidence_dir=evidence_dir,
            min_rows=5000,
            min_symbols=20,
            min_accuracy=0.50,
        )

    assert payload["ready_for_observe_only_validation"] is True
    assert payload["ready_for_live_promotion"] is False
    assert payload["promotion_evidence_blockers"]
    assert len(payload["promotion_evidence"]) == 12


def test_model_validation_governance_blocks_simple_split_candidate_registration():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        candidate_dir = base / "candidates"
        evidence_dir = base / "evidence"
        candidate_dir.mkdir()
        evidence_dir.mkdir()
        registry_path = base / "registry.json"
        registry_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
        _write_diag(
            candidate_dir,
            label="triple_barrier_label",
            validation_method="chronological_80_20_observe_only",
        )

        payload = build_model_validation_governance_payload(
            candidate_dir=candidate_dir,
            registry_path=registry_path,
            promotion_evidence_dir=evidence_dir,
            min_rows=5000,
            min_symbols=20,
            min_accuracy=0.50,
        )

    assert payload["ready_for_observe_only_validation"] is True
    assert payload["ready_for_candidate_registration"] is False
    assert any(
        "simple_split_not_candidate_registration_eligible" in blocker
        for blocker in payload["candidate_registration_blockers"]
    )


def test_model_validation_governance_prefers_better_candidate_over_newer_partial():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        candidate_dir = base / "candidates"
        evidence_dir = base / "evidence"
        candidate_dir.mkdir()
        evidence_dir.mkdir()
        registry_path = base / "registry.json"
        registry_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
        _write_diag(
            candidate_dir,
            label="triple_barrier_label",
            accuracy=0.76,
            rows_loaded=6000,
            generated_at="2026-06-07T12:00:00+00:00",
            trained=True,
        )
        _write_diag(
            candidate_dir,
            label="triple_barrier_label",
            accuracy=None,
            rows_loaded=59,
            generated_at="2026-06-08T12:00:00+00:00",
            trained=False,
        )

        payload = build_model_validation_governance_payload(
            candidate_dir=candidate_dir,
            registry_path=registry_path,
            promotion_evidence_dir=evidence_dir,
            min_rows=5000,
            min_symbols=20,
            min_accuracy=0.50,
        )

    candidate = payload["candidates"][0]
    assert candidate["status"] == "observe_only_ready"
    assert candidate["rows_loaded"] == 6000
    assert candidate["accuracy"] == 0.76


def main():
    tests = [
        test_model_validation_governance_accepts_observe_only_candidates,
        test_model_validation_governance_blocks_live_registry_status,
        test_model_validation_governance_requires_promotion_evidence_for_live_readiness,
        test_model_validation_governance_blocks_simple_split_candidate_registration,
        test_model_validation_governance_prefers_better_candidate_over_newer_partial,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} model validation governance tests passed.")


if __name__ == "__main__":
    main()
