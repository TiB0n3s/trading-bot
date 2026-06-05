#!/usr/bin/env python3
"""Tests for focused historical-bar retry planning."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.historical_bar_retry_missing import build_retry_plan  # noqa: E402


def _write_cache(base_dir: Path, symbol: str, start: str, end: str) -> None:
    cache_dir = base_dir / "data" / "historical_bars" / "polygon_1min"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{symbol}_1min_rth_{start}_{end}.csv").write_text("x\n", encoding="utf-8")


def _write_manifest(base_dir: Path) -> None:
    manifest_dir = base_dir / "data" / "historical_bars" / "polygon_1min" / "backfill_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "historical_bar_backfill_20260605T120000Z.json").write_text(
        json.dumps(
            {
                "attempted_chunks": 1,
                "successful_chunks": 0,
                "errors": ["VZ 2026-04-22..2026-05-21: TimeoutError: read timed out"],
            }
        ),
        encoding="utf-8",
    )


def test_retry_plan_prioritizes_manifest_error_and_incomplete_symbols():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _write_cache(base_dir, "AAPL", "2026-01-01", "2026-01-03")
        _write_manifest(base_dir)

        payload = build_retry_plan(
            base_dir=base_dir,
            start_date="2026-01-01",
            end_date="2026-01-03",
            min_days=3,
            max_symbols=3,
            manifest_limit=5,
        )

    assert payload["report_version"] == "historical_bar_retry_plan_v1"
    assert payload["recent_manifest_errors"] == 1
    assert payload["selected_symbols"][0] == "VZ"
    assert "recent_manifest_error" in payload["selection_reasons"]["VZ"]
    assert "--skip-existing-cache" in payload["command"]
    assert ",".join(payload["selected_symbols"]) in payload["command"]


def main():
    test_retry_plan_prioritizes_manifest_error_and_incomplete_symbols()
    print("historical bar retry missing tests passed")


if __name__ == "__main__":
    main()
