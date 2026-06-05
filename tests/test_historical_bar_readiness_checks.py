#!/usr/bin/env python3
"""Tests for consolidated historical bar ML readiness reporting."""

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

from services.ops_checks.historical_bar_readiness_checks import (  # noqa: E402
    run_historical_bar_readiness,
)


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                feature_version TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                vwap REAL,
                sma_20 REAL,
                bollinger_percent_b_20 REAL,
                rolling_volatility_20_pct REAL,
                day_of_week INTEGER,
                minute_of_day INTEGER,
                ema_12 REAL,
                ema_26 REAL,
                macd REAL,
                rsi_14 REAL,
                atr_20_pct REAL,
                volume_ratio_20 REAL,
                cumulative_volume_delta REAL,
                vpin_toxicity_20 REAL,
                fractional_diff_zscore_20 REAL,
                triple_barrier_label INTEGER,
                trend_scan_label INTEGER
            )
            """
        )
        rows = []
        for day in range(1, 4):
            rows.append(
                (
                    "AAPL",
                    f"2026-01-{day:02d}T09:30:00-05:00",
                    "1m",
                    "v4",
                    100.0,
                    101.0,
                    99.0,
                    100.5,
                    1000.0,
                    100.2,
                    100.0,
                    0.5,
                    1.2,
                    1,
                    570,
                    100.1,
                    100.0,
                    0.1,
                    55.0,
                    0.9,
                    1.1,
                    10.0,
                    0.4,
                    0.2,
                    1,
                    1,
                )
            )
        rows.append(rows[-1])
        con.executemany(
            """
            INSERT INTO bar_pattern_features VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            rows,
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
    (manifest_dir / "historical_bar_backfill_20260102T120000Z.json").write_text(
        json.dumps(
            {
                "attempted_chunks": 1,
                "successful_chunks": 1,
                "skipped_chunks": 0,
                "cached_rows": 3,
                "persisted_pattern_rows": 3,
                "errors": [],
            }
        ),
        encoding="utf-8",
    )


def test_historical_bar_readiness_reports_quality_and_hook_status():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _build_db(base_dir / "trades.db")
        _write_manifest(base_dir)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = run_historical_bar_readiness(
                base_dir=base_dir,
                start_date="2026-01-01",
                end_date="2026-01-03",
                min_days=3,
                min_symbols=1,
                include_db_quality=True,
                include_duplicate_scan=True,
                limit=5,
            )

    out = buf.getvalue()
    assert ok is False
    assert "historical_bar_readiness_v1" in out
    assert "duplicate_rows             : 1" in out
    assert "completion_hook_ready      : False" in out
    assert "Feature missing-rate watchlist" in out
    assert "historical bars are not yet ready" in out


if __name__ == "__main__":
    test_historical_bar_readiness_reports_quality_and_hook_status()
    print("[OK] test_historical_bar_readiness_reports_quality_and_hook_status")
    print("\nAll 1 historical bar readiness tests passed.")
