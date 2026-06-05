#!/usr/bin/env python3
"""Tests for symbol-universe retraining/backfill pipeline entrypoint."""

from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import symbol_universe_retrain
from services import symbol_universe_retraining_service as svc


def test_symbol_universe_retrain_dry_run_would_backfill_added_symbols():
    original_symbols = svc.APPROVED_SYMBOLS_LIST[:]
    old_argv = sys.argv[:]
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        db_path = Path(tmp) / "trades.db"
        service = svc.SymbolUniverseRetrainingService(
            state_path=state_path,
            db_path=db_path,
        )
        service.initialize_baseline()
        try:
            svc.APPROVED_SYMBOLS_LIST.append("ZZZZ")
            sys.argv = [
                "pipeline/symbol_universe_retrain.py",
                "--date",
                "2026-06-05",
                "--state-path",
                str(state_path),
                "--db-path",
                str(db_path),
                "--min-bar-rows",
                "10",
                "--min-bar-days",
                "2",
                "--dry-run",
            ]
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = symbol_universe_retrain.main()
        finally:
            svc.APPROVED_SYMBOLS_LIST[:] = original_symbols
            sys.argv = old_argv

    out = buf.getvalue()
    assert code == 0
    assert "status               : would_backfill_added_symbols" in out
    assert "added_symbols        : ZZZZ" in out
    assert "ZZZZ:fewer_than_10_bar_pattern_rows" in out


def test_added_symbol_backfill_command_uses_historical_bar_pipeline():
    class Result:
        returncode = 0

    original_run = symbol_universe_retrain.subprocess.run
    calls = []
    try:
        symbol_universe_retrain.subprocess.run = lambda cmd, cwd=None: calls.append((cmd, cwd)) or Result()
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
            },
        )()
        code = symbol_universe_retrain._run_added_symbol_backfill(
            args,
            added_symbols=["ZZZZ"],
        )
    finally:
        symbol_universe_retrain.subprocess.run = original_run

    assert code == 0
    cmd, cwd = calls[0]
    assert cwd == ROOT
    assert str(ROOT / "pipeline" / "historical_bar_backfill.py") in cmd
    assert "--skip-existing-cache" in cmd
    assert "ZZZZ" in cmd


def main():
    tests = [
        test_symbol_universe_retrain_dry_run_would_backfill_added_symbols,
        test_added_symbol_backfill_command_uses_historical_bar_pipeline,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} symbol-universe retrain pipeline tests passed.")


if __name__ == "__main__":
    main()
