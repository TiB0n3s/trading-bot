#!/usr/bin/env python3
"""Tests for external-symbol candidate refresh pipeline."""

from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import external_symbol_candidate_refresh as pipeline  # noqa: E402


def test_external_symbol_candidate_refresh_dry_run_reports_would_backfill():
    old_build = pipeline.build_external_symbol_discovery_payload
    old_argv = sys.argv[:]
    try:
        pipeline.build_external_symbol_discovery_payload = lambda **kwargs: {
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "findings": [
                {
                    "symbol": "XYZ",
                    "symbol_class": "unknown_external",
                    "mentions": 3,
                    "trusted_mentions": 2,
                    "linked_approved_symbols": ["AAPL"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            sys.argv = [
                "pipeline/external_symbol_candidate_refresh.py",
                "--date",
                "2026-06-05",
                "--state-path",
                str(Path(tmp) / "state.json"),
                "--db-path",
                str(Path(tmp) / "trades.db"),
                "--min-bar-rows",
                "20",
                "--min-bar-days",
                "2",
                "--dry-run",
            ]
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = pipeline.main()
    finally:
        pipeline.build_external_symbol_discovery_payload = old_build
        sys.argv = old_argv

    out = buf.getvalue()
    assert code == 0
    assert "status               : would_backfill_candidates" in out
    assert "backfill_symbols     : XYZ" in out


def test_external_symbol_candidate_backfill_command_uses_historical_bar_pipeline():
    class Result:
        returncode = 0

    old_run = pipeline.subprocess.run
    calls = []
    try:
        pipeline.subprocess.run = lambda cmd, cwd=None: calls.append((cmd, cwd)) or Result()
        args = type(
            "Args",
            (),
            {
                "backfill_start_date": "2024-06-01",
                "backfill_end_date": None,
                "date": "2026-06-05",
                "backfill_chunk_days": 30,
                "backfill_horizon_bars": 20,
                "backfill_retry_attempts": 2,
                "backfill_retry_sleep_seconds": 15.0,
                "backfill_request_sleep_seconds": 0.25,
                "max_chunks": 3,
            },
        )()
        code = pipeline._run_backfill(args, ["XYZ"])
    finally:
        pipeline.subprocess.run = old_run

    assert code == 0
    cmd, cwd = calls[0]
    assert cwd == ROOT
    assert str(ROOT / "pipeline" / "historical_bar_backfill.py") in cmd
    assert "--skip-existing-cache" in cmd
    assert "XYZ" in cmd
    assert "--max-chunks" in cmd


def main():
    test_external_symbol_candidate_refresh_dry_run_reports_would_backfill()
    test_external_symbol_candidate_backfill_command_uses_historical_bar_pipeline()
    print("external symbol candidate refresh pipeline tests passed")


if __name__ == "__main__":
    main()
