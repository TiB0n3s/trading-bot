#!/usr/bin/env python3
"""Tests for Polygon historical bar backfill progress reporting."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ops_checks.historical_bar_progress_checks import (  # noqa: E402
    run_historical_bar_progress,
)


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                triple_barrier_label INTEGER,
                trend_scan_label INTEGER
            )
            """
        )
        for day in range(1, 4):
            con.execute(
                """
                INSERT INTO bar_pattern_features
                    (symbol, bar_timestamp, timeframe, triple_barrier_label, trend_scan_label)
                VALUES ('AAPL', ?, '1m', 1, 1)
                """,
                (f"2026-01-{day:02d}T09:30:00-05:00",),
            )
        con.execute(
            """
            INSERT INTO bar_pattern_features
                (symbol, bar_timestamp, timeframe, triple_barrier_label, trend_scan_label)
            VALUES ('MSFT', '2026-01-01T09:30:00-05:00', '1m', 1, 1)
            """
        )


def _write_manifest(base_dir: Path) -> None:
    manifest_dir = (
        base_dir
        / "data"
        / "historical_bars"
        / "polygon_1min"
        / "backfill_manifests"
    )
    manifest_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "attempted_chunks": 2,
        "successful_chunks": 1,
        "skipped_chunks": 0,
        "cached_rows": 100,
        "persisted_pattern_rows": 90,
        "errors": ["AAPL 2026-01-01..2026-01-30: HTTPError: 429"],
    }
    (manifest_dir / "historical_bar_backfill_20260102T120000Z.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    cache_dir = base_dir / "data" / "historical_bars" / "polygon_1min"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "MSFT_1min_rth_2026-01-01_2026-01-03.csv").write_text(
        "Timestamp,Open,High,Low,Close,Volume\n",
        encoding="utf-8",
    )


def test_historical_bar_progress_reports_manifest_and_priority_symbols():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _build_db(base_dir / "trades.db")
        _write_manifest(base_dir)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = run_historical_bar_progress(
                base_dir=base_dir,
                start_date="2026-01-01",
                end_date="2026-01-03",
                min_days=3,
                min_symbols=2,
                limit=100,
            )

    out = buf.getvalue()
    assert ok is False
    assert "historical_bar_progress_v1" in out
    assert "recent_manifest_errors  : 1" in out
    assert "file                  : historical_bar_backfill_20260102T120000Z.json" in out
    assert "MSFT" in out
    assert "empty=1" in out
    assert "too few cached symbols meet" in out


if __name__ == "__main__":
    test_historical_bar_progress_reports_manifest_and_priority_symbols()
    print("[OK] test_historical_bar_progress_reports_manifest_and_priority_symbols")
    print("\nAll 1 historical bar progress tests passed.")
