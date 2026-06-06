#!/usr/bin/env python3
"""Tests for historical bar observe-only training row fetches."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.historical_bar_training_repo import (  # noqa: E402
    fetch_historical_bar_training_rows,
)
from services.bar_pattern_feature_service import BAR_PATTERN_FEATURE_VERSION  # noqa: E402


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
                ema_12 REAL,
                ema_26 REAL,
                macd REAL,
                rsi_14 REAL,
                triple_barrier_label INTEGER,
                trend_scan_label INTEGER
            )
            """
        )
        con.executemany(
            """
            INSERT INTO bar_pattern_features VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    "AAPL",
                    "2026-01-02T14:30:00+00:00",
                    "1m",
                    BAR_PATTERN_FEATURE_VERSION,
                    100,
                    101,
                    99,
                    100.5,
                    1000,
                    100,
                    100,
                    0.1,
                    55,
                    1,
                    1,
                ),
                (
                    "AAPL",
                    "2026-01-02T14:31:00+00:00",
                    "1m",
                    "v4",
                    101,
                    102,
                    100,
                    101.5,
                    1000,
                    101,
                    101,
                    0.2,
                    60,
                    -1,
                    -1,
                ),
                (
                    "AAPL",
                    "2026-01-02T14:32:00+00:00",
                    "1m",
                    "legacy_v3",
                    102,
                    103,
                    101,
                    102.5,
                    1000,
                    102,
                    102,
                    0.3,
                    65,
                    1,
                    1,
                ),
                (
                    "MSFT",
                    "2026-01-02T14:33:00+00:00",
                    "5m",
                    BAR_PATTERN_FEATURE_VERSION,
                    200,
                    201,
                    199,
                    200.5,
                    1000,
                    200,
                    200,
                    0.1,
                    55,
                    1,
                    1,
                ),
            ],
        )


def test_fetch_historical_bar_training_rows_filters_current_1m_labels():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        _build_db(db_path)
        rows = fetch_historical_bar_training_rows(
            db_path=db_path,
            start_date="2026-01-01",
            end_date="2026-01-03",
            label_target="triple_barrier_label",
            limit=10,
        )

    assert [row["feature_version"] for row in rows] == [
        BAR_PATTERN_FEATURE_VERSION,
        "v4",
    ]
    assert [row["triple_barrier_label"] for row in rows] == [1, -1]
    assert rows[0]["bar_timestamp"] < rows[1]["bar_timestamp"]


def test_fetch_historical_bar_training_rows_can_balance_per_symbol():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        _build_db(db_path)
        rows = fetch_historical_bar_training_rows(
            db_path=db_path,
            start_date="2026-01-01",
            end_date="2026-01-03",
            label_target="triple_barrier_label",
            rows_per_symbol=1,
            limit=10,
        )

    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["symbol_row_number"] == 1


if __name__ == "__main__":
    test_fetch_historical_bar_training_rows_filters_current_1m_labels()
    print("[OK] test_fetch_historical_bar_training_rows_filters_current_1m_labels")
    test_fetch_historical_bar_training_rows_can_balance_per_symbol()
    print("[OK] test_fetch_historical_bar_training_rows_can_balance_per_symbol")
