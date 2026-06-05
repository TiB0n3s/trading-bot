#!/usr/bin/env python3
"""Tests for historical bar completion training hook."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import historical_bar_completion_hook as hook


def _write_chunk(base_dir: Path, symbol: str, start: str, end: str) -> None:
    cache_dir = base_dir / "data" / "historical_bars" / "polygon_1min"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{symbol}_1min_rth_{start}_{end}.csv").write_text("Timestamp,Close\n", encoding="utf-8")


def _write_manifest(base_dir: Path, *, errors=None) -> None:
    manifest_dir = base_dir / "data" / "historical_bars" / "polygon_1min" / "backfill_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "historical_bar_backfill_20260605T120000Z.json").write_text(
        json.dumps({"attempted_chunks": 1, "successful_chunks": 1, "errors": errors or []}),
        encoding="utf-8",
    )


def test_completion_assessment_not_ready_with_manifest_error():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _write_chunk(base_dir, "AAPL", "2026-01-01", "2026-01-05")
        _write_manifest(base_dir, errors=["timeout"])
        old_base = hook.BASE_DIR
        try:
            hook.BASE_DIR = base_dir
            args = type(
                "Args",
                (),
                {
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-05",
                    "min_days": 3,
                    "min_symbols": 1,
                },
            )()
            payload = hook.build_completion_assessment(args)
        finally:
            hook.BASE_DIR = old_base

    assert payload["status"] == "not_ready"
    assert payload["readiness"]["symbols_ready"] == 1
    assert payload["readiness"]["recent_manifest_errors"] == 1


def test_completion_assessment_ready_without_errors():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _write_chunk(base_dir, "AAPL", "2026-01-01", "2026-01-05")
        _write_manifest(base_dir)
        old_base = hook.BASE_DIR
        try:
            hook.BASE_DIR = base_dir
            args = type(
                "Args",
                (),
                {
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-05",
                    "min_days": 3,
                    "min_symbols": 1,
                },
            )()
            payload = hook.build_completion_assessment(args)
        finally:
            hook.BASE_DIR = old_base

    assert payload["status"] == "ready"
    assert payload["training_allowed"] is True
    assert payload["readiness"]["coverage_hash"]


def main():
    tests = [
        test_completion_assessment_not_ready_with_manifest_error,
        test_completion_assessment_ready_without_errors,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} historical bar completion hook tests passed.")


if __name__ == "__main__":
    main()
