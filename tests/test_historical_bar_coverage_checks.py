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


def _build_db(
    path: Path,
    *,
    days: int = 3,
    symbols: tuple[str, ...] = ("AAPL", "MSFT"),
    include_raw_contract: bool = False,
) -> None:
    with sqlite3.connect(path) as con:
        raw_contract_columns = """
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                vwap REAL,
                bar_interval_start_ts TEXT,
                ema_12 REAL,
                ema_26 REAL,
                macd REAL,
                macd_signal REAL,
                rsi_14 REAL,
        """ if include_raw_contract else ""
        con.execute(
            f"""
            CREATE TABLE bar_pattern_features (
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                {raw_contract_columns}
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
                timestamp = f"2026-01-{day:02d}T09:30:00-05:00"
                if include_raw_contract:
                    con.execute(
                        """
                        INSERT INTO bar_pattern_features (
                            symbol, bar_timestamp, timeframe,
                            open, high, low, close, volume, vwap,
                            bar_interval_start_ts,
                            ema_12, ema_26, macd, macd_signal, rsi_14,
                            triple_barrier_label, trend_scan_label,
                            fractional_diff_zscore_20, vpin_toxicity_20,
                            cumulative_volume_delta
                        ) VALUES (?, ?, '1m', 100, 101, 99, 100.5, 10000, 100.4, ?, 100.2, 100.0, 0.2, 0.1, 62, 1, 1, 0.4, 0.2, 1200)
                        """,
                        (symbol, timestamp, timestamp),
                    )
                else:
                    con.execute(
                        """
                        INSERT INTO bar_pattern_features (
                            symbol, bar_timestamp, timeframe,
                            triple_barrier_label, trend_scan_label,
                            fractional_diff_zscore_20, vpin_toxicity_20,
                            cumulative_volume_delta
                        ) VALUES (?, ?, '1m', 1, 1, 0.4, 0.2, 1200)
                        """,
                        (symbol, timestamp),
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
    assert "raw_bar_contract        : 0.00%" in out
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


def test_historical_bar_coverage_reports_raw_contract_and_indicator_coverage():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _build_db(base_dir / "trades.db", days=3, include_raw_contract=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = run_historical_bar_coverage(
                base_dir=base_dir,
                min_days=3,
                min_symbols=2,
            )

    out = buf.getvalue()
    assert ok is True
    assert "raw_bar_contract        : 100.00%" in out
    assert "technical_indicators    : 100.00%" in out


if __name__ == "__main__":
    test_historical_bar_coverage_reports_not_ready_for_short_history()
    print("[OK] test_historical_bar_coverage_reports_not_ready_for_short_history")
    test_historical_bar_coverage_passes_when_thresholds_met()
    print("[OK] test_historical_bar_coverage_passes_when_thresholds_met")
    test_historical_bar_coverage_reports_raw_contract_and_indicator_coverage()
    print("[OK] test_historical_bar_coverage_reports_raw_contract_and_indicator_coverage")
    print("\nAll 3 historical bar coverage tests passed.")
