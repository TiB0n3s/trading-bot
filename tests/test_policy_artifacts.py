#!/usr/bin/env python3
"""Tests for policy artifact registry and rollback controls."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy_artifacts import (
    POLICY_ARTIFACT_FILES,
    policy_artifact_status,
    register_policy_artifact_set,
    rollback_policy_artifacts,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def write_artifacts(base: Path, suffix: str) -> None:
    for name in POLICY_ARTIFACT_FILES:
        payload = {
            "generated_at": f"2026-05-27T12:00:00+00:00-{suffix}",
            "artifact": name,
            "value": suffix,
        }
        (base / name).write_text(json.dumps(payload, sort_keys=True) + "\n")


def test_register_policy_artifact_set_marks_known_good():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        write_artifacts(base, "v1")

        entry = register_policy_artifact_set(
            base,
            label="test",
            source="unit_test",
            mark_known_good=True,
        )
        status = policy_artifact_status(base)

        assert_true(entry["artifact_set_id"], "artifact set id")
        assert_equal(status["registry"]["entry_count"], 1, "registry count")
        assert_equal(
            status["registry"]["known_good"]["artifact_set_id"],
            entry["artifact_set_id"],
            "known-good pointer",
        )
        assert_equal(status["state_hash"], entry["state_hash"], "state hash")


def test_rollback_restores_known_good_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        write_artifacts(base, "v1")
        entry = register_policy_artifact_set(
            base,
            label="test",
            source="unit_test",
            mark_known_good=True,
        )

        write_artifacts(base, "v2")
        before = json.loads((base / "strategy_memory.json").read_text())
        assert_equal(before["value"], "v2", "pre-rollback value")

        result = rollback_policy_artifacts(base)
        after = json.loads((base / "strategy_memory.json").read_text())

        assert_equal(result["artifact_set_id"], entry["artifact_set_id"], "rollback id")
        assert_equal(after["value"], "v1", "post-rollback value")
        assert_equal(len(result["restored_files"]), len(POLICY_ARTIFACT_FILES), "restored files")


def test_rollback_dry_run_does_not_modify_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        write_artifacts(base, "v1")
        register_policy_artifact_set(base, label="test", source="unit_test", mark_known_good=True)
        write_artifacts(base, "v2")

        result = rollback_policy_artifacts(base, dry_run=True)
        after = json.loads((base / "strategy_memory.json").read_text())

        assert_equal(result["dry_run"], True, "dry run")
        assert_equal(after["value"], "v2", "dry-run preserves current file")


if __name__ == "__main__":
    test_register_policy_artifact_set_marks_known_good()
    print("[OK] test_register_policy_artifact_set_marks_known_good")
    test_rollback_restores_known_good_artifacts()
    print("[OK] test_rollback_restores_known_good_artifacts")
    test_rollback_dry_run_does_not_modify_artifacts()
    print("[OK] test_rollback_dry_run_does_not_modify_artifacts")
    print("\nAll 3 policy artifact tests passed.")
