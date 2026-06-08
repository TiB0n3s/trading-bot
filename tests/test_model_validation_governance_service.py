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

from services.model_validation_governance_service import (  # noqa: E402
    build_model_validation_governance_payload,
)


def _write_diag(candidate_dir: Path, *, label: str, accuracy: float = 0.76) -> None:
    payload = {
        "runtime_effect": "observe_only_no_live_authority",
        "model_id": f"historical_bar_{label}_test",
        "label_target": label,
        "generated_at": "2026-06-08T12:00:00+00:00",
        "rows_loaded": 6000,
        "symbol_count": 59,
        "training": {"trained": True, "accuracy": accuracy},
    }
    (candidate_dir / f"historical_bar_{label}_test.diagnostic.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_model_validation_governance_accepts_observe_only_candidates():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        candidate_dir = base / "candidates"
        candidate_dir.mkdir()
        registry_path = base / "registry.json"
        registry_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
        _write_diag(candidate_dir, label="triple_barrier_label")

        payload = build_model_validation_governance_payload(
            candidate_dir=candidate_dir,
            registry_path=registry_path,
            min_rows=5000,
            min_symbols=20,
            min_accuracy=0.50,
        )

    assert payload["ready_for_observe_only_validation"] is True
    assert payload["ready_for_live_promotion"] is False
    assert payload["blockers"] == []
    assert payload["ready_label_count"] == 1


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
    assert len(payload["promotion_evidence"]) == 5


def main():
    tests = [
        test_model_validation_governance_accepts_observe_only_candidates,
        test_model_validation_governance_blocks_live_registry_status,
        test_model_validation_governance_requires_promotion_evidence_for_live_readiness,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} model validation governance tests passed.")


if __name__ == "__main__":
    main()
