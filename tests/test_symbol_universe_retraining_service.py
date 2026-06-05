#!/usr/bin/env python3
"""Tests for approved-symbol universe retraining trigger state."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import symbol_universe_retraining_service as svc


def _write_bar_rows(db_path: Path, symbol: str, *, days: int, rows_per_day: int = 10) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                symbol TEXT,
                bar_timestamp TEXT
            )
            """
        )
        rows = []
        for day in range(days):
            for minute in range(rows_per_day):
                rows.append((symbol, f"2026-05-{day + 1:02d}T10:{minute:02d}:00+00:00"))
        con.executemany(
            "INSERT INTO bar_pattern_features (symbol, bar_timestamp) VALUES (?, ?)",
            rows,
        )


def test_universe_trigger_initializes_baseline_without_training():
    with tempfile.TemporaryDirectory() as tmp:
        service = svc.SymbolUniverseRetrainingService(
            state_path=Path(tmp) / "state.json",
            db_path=Path(tmp) / "trades.db",
        )
        assessment = service.assess()
        assert assessment.status == "needs_baseline"
        assert assessment.retraining_required is False

        state = service.initialize_baseline()
        assert state["last_trained_snapshot"]["universe_hash"] == svc.approved_universe_snapshot()["universe_hash"]


def test_added_symbol_waits_for_bar_coverage():
    original_symbols = svc.APPROVED_SYMBOLS_LIST[:]
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        db_path = Path(tmp) / "trades.db"
        service = svc.SymbolUniverseRetrainingService(state_path=state_path, db_path=db_path)
        service.initialize_baseline()
        try:
            svc.APPROVED_SYMBOLS_LIST.append("ZZZZ")
            assessment = service.assess(min_bar_rows=10, min_bar_days=2)
            assert assessment.status == "pending_bar_coverage"
            assert assessment.retraining_required is True
            assert assessment.retraining_allowed is False
            assert "ZZZZ" in assessment.added_symbols
            assert any("ZZZZ:fewer_than_10_bar_pattern_rows" in item for item in assessment.blockers)
        finally:
            svc.APPROVED_SYMBOLS_LIST[:] = original_symbols


def test_added_symbol_with_coverage_allows_retraining():
    original_symbols = svc.APPROVED_SYMBOLS_LIST[:]
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        db_path = Path(tmp) / "trades.db"
        service = svc.SymbolUniverseRetrainingService(state_path=state_path, db_path=db_path)
        service.initialize_baseline()
        _write_bar_rows(db_path, "ZZZZ", days=3, rows_per_day=5)
        try:
            svc.APPROVED_SYMBOLS_LIST.append("ZZZZ")
            assessment = service.assess(min_bar_rows=10, min_bar_days=2)
            assert assessment.status == "ready_for_retraining"
            assert assessment.retraining_required is True
            assert assessment.retraining_allowed is True
            assert assessment.coverage["ZZZZ"]["rows"] == 15
            assert assessment.coverage["ZZZZ"]["trading_days"] == 3
        finally:
            svc.APPROVED_SYMBOLS_LIST[:] = original_symbols


def main():
    tests = [
        test_universe_trigger_initializes_baseline_without_training,
        test_added_symbol_waits_for_bar_coverage,
        test_added_symbol_with_coverage_allows_retraining,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} symbol-universe retraining tests passed.")


if __name__ == "__main__":
    main()
