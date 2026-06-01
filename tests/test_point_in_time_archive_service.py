#!/usr/bin/env python3
"""Tests for point-in-time context archive snapshots."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.point_in_time_archive_service import PointInTimeArchiveService


def test_point_in_time_archive_writes_context_hashes_and_refs():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "market_context.json").write_text(
            json.dumps({"generated_at": "2026-06-01T08:00:00+00:00", "macro": "risk_on"})
        )
        (base / "symbol_overrides.json").write_text(json.dumps({"disabled_symbols": []}))
        artifacts = base / "policy_artifacts"
        artifacts.mkdir()
        (artifacts / "policy.json").write_text('{"version":"test"}')

        result = PointInTimeArchiveService(base_dir=base).archive_current_context(
            archive_date="2026-06-01",
            reason="unit_test",
        )

        assert result.archive_path.exists()
        assert result.payload["version"] == "point_in_time_archive_v1"
        assert result.payload["market_context_hash"]
        assert result.payload["symbol_overrides_hash"]
        assert "policy.json" in result.payload["policy_artifact_refs"]
        archived = json.loads(result.archive_path.read_text())
        assert archived["archive_reason"] == "unit_test"


def main():
    tests = [test_point_in_time_archive_writes_context_hashes_and_refs]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} point-in-time archive tests passed.")


if __name__ == "__main__":
    main()
