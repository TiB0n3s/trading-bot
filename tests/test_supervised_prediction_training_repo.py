#!/usr/bin/env python3
"""Tests for supervised prediction training repository point-in-time reads."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.supervised_prediction_training_repo import fetch_training_rows


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE feature_snapshots (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                timestamp TEXT,
                feature_available_at TEXT,
                ret_1m REAL,
                ret_5m REAL,
                ret_15m REAL,
                range_pos_15m REAL,
                distance_from_vwap REAL,
                volume_ratio_5m REAL,
                relative_strength_5m REAL,
                spread_pct REAL,
                setup_score REAL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE labeled_setups (
                snapshot_id INTEGER,
                ret_fwd_5m REAL,
                ret_fwd_15m REAL,
                ret_fwd_30m REAL
            )
            """
        )
        for idx, available_at in (
            (1, "2026-06-03T10:00:00+00:00"),
            (2, "2026-06-03T22:00:00+00:00"),
        ):
            con.execute(
                """
                INSERT INTO feature_snapshots (
                    id, symbol, timestamp, feature_available_at,
                    ret_1m, ret_5m, ret_15m, range_pos_15m,
                    distance_from_vwap, volume_ratio_5m,
                    relative_strength_5m, spread_pct, setup_score
                ) VALUES (?, 'AAPL', ?, ?, 1, 2, 3, 0.5, 1, 1.2, 0.3, 0.01, 70)
                """,
                (idx, f"2026-06-03T0{idx}:00:00+00:00", available_at),
            )
            con.execute(
                """
                INSERT INTO labeled_setups (
                    snapshot_id, ret_fwd_5m, ret_fwd_15m, ret_fwd_30m
                ) VALUES (?, 0.1, 0.2, 0.3)
                """,
                (idx,),
            )


def test_fetch_training_rows_respects_feature_available_at_cutoff():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        _build_db(db_path)

        rows = fetch_training_rows(
            db_path=db_path,
            prediction_time_cutoff="2026-06-03T12:00:00+00:00",
        )

    assert len(rows) == 1
    assert rows[0]["timestamp"] == "2026-06-03T01:00:00+00:00"


if __name__ == "__main__":
    tests = [test_fetch_training_rows_respects_feature_available_at_cutoff]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} supervised prediction training repo tests passed.")
