#!/usr/bin/env python3
"""Tests for live bar-pattern feature capture verification."""

from __future__ import annotations

import io
import sqlite3
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ops_checks.live_bar_pattern_capture_checks import (
    run_live_bar_pattern_capture_report,
)


def _create_db(tmp_path: Path, target_date: str) -> None:
    with sqlite3.connect(tmp_path / "trades.db") as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                bar_source TEXT,
                bar_feed TEXT,
                close REAL,
                volume REAL,
                vpin_toxicity_20 REAL,
                cumulative_volume_delta REAL,
                trend_scan_label INTEGER,
                triple_barrier_label INTEGER,
                feature_version TEXT,
                runtime_effect TEXT,
                created_at TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO bar_pattern_features (
                symbol, bar_timestamp, timeframe, bar_source, bar_feed, close,
                volume, vpin_toxicity_20, cumulative_volume_delta,
                trend_scan_label, triple_barrier_label, feature_version,
                runtime_effect, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "AAPL",
                    f"{target_date}T14:32:00+00:00",
                    "1m",
                    "session_momentum_market_data",
                    "iex",
                    197.25,
                    123456,
                    0.18,
                    4200,
                    1,
                    1,
                    "bar_pattern_feature_v4",
                    "observe_only_pattern_learning_no_live_authority",
                    datetime.now(timezone.utc).isoformat(),
                ),
                (
                    "MSFT",
                    f"{target_date}T14:31:00+00:00",
                    "1m",
                    "session_momentum_market_data",
                    "iex",
                    421.10,
                    65432,
                    0.08,
                    2100,
                    0,
                    1,
                    "bar_pattern_feature_v4",
                    "observe_only_pattern_learning_no_live_authority",
                    datetime.now(timezone.utc).isoformat(),
                ),
            ],
        )


def test_live_bar_pattern_capture_reports_fresh_rows(tmp_path):
    target_date = datetime.now(timezone.utc).date().isoformat()
    _create_db(tmp_path, target_date)

    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = run_live_bar_pattern_capture_report(
            target_date,
            base_dir=tmp_path,
            max_age_minutes=60,
            min_symbols=2,
        )

    output = buf.getvalue()
    assert ok is True
    assert "rows_today              : 2" in output
    assert "symbols_today           : 2" in output
    assert "session_momentum_market_data" in output
    assert "[OK] live bar-pattern capture evidence is available" in output


def test_live_bar_pattern_capture_fails_missing_table(tmp_path):
    with sqlite3.connect(tmp_path / "trades.db"):
        pass

    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = run_live_bar_pattern_capture_report(
            "2026-06-08",
            base_dir=tmp_path,
        )

    assert ok is False
    assert "bar_pattern_features table is missing" in buf.getvalue()


if __name__ == "__main__":
    import tempfile

    tests = [
        test_live_bar_pattern_capture_reports_fresh_rows,
        test_live_bar_pattern_capture_fails_missing_table,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} live bar-pattern capture tests passed.")
