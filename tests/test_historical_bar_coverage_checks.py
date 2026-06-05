#!/usr/bin/env python3
"""Tests for historical bar ML feature coverage reporting."""

from __future__ import annotations

import io
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ops_checks.historical_bar_coverage_checks import run_historical_bar_coverage  # noqa: E402


def _build_db(path: Path, *, days: int = 3, symbols: tuple[str, ...] = ("AAPL", "MSFT")) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                triple_barrier_label INTEGER,
                trend_scan_label INTEGER,
                fractional_diff_zscore_20 REAL,
                vpin_toxicity_20 REAL,
                cumulative_volume_delta REAL
            )
            """
        )
        for day in range(1, days + 1):
            for symbol in symbols:
                con.execute(
                    """
                    INSERT INTO bar_pattern_features (
                        symbol, bar_timestamp, timeframe,
                        triple_barrier_label, trend_scan_label,
                        fractional_diff_zscore_20, vpin_toxicity_20,
                        cumulative_volume_delta
                    ) VALUES (?, ?, '1m', 1, 1, 0.4, 0.2, 1200)
                    """,
                    (symbol, f"2026-01-{day:02d}T09:30:00-05:00"),
                )


def test_historical_bar_coverage_reports_not_ready_for_short_history():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _build_db(base_dir / "trades.db", days=3)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = run_historical_bar_coverage(
                base_dir=base_dir,
                min_days=10,
                min_symbols=2,
            )

    out = buf.getvalue()
    assert ok is False
    assert "historical_bar_coverage_v1" in out
    assert "market_dates            : 3" in out
    assert "training_ready          : False" in out


def test_historical_bar_coverage_passes_when_thresholds_met():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _build_db(base_dir / "trades.db", days=3)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = run_historical_bar_coverage(
                base_dir=base_dir,
                min_days=3,
                min_symbols=2,
            )

    out = buf.getvalue()
    assert ok is True
    assert "training_ready          : True" in out
    assert "[OK] historical bar coverage meets configured ML training floor" in out


if __name__ == "__main__":
    test_historical_bar_coverage_reports_not_ready_for_short_history()
    print("[OK] test_historical_bar_coverage_reports_not_ready_for_short_history")
    test_historical_bar_coverage_passes_when_thresholds_met()
    print("[OK] test_historical_bar_coverage_passes_when_thresholds_met")
    print("\nAll 2 historical bar coverage tests passed.")
