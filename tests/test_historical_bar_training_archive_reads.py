#!/usr/bin/env python3
"""Historical-bar training reads cold archive rows."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.historical_bar_training_repo import fetch_historical_bar_training_rows


def _create_bar_table(con: sqlite3.Connection, *, archive: bool = False) -> None:
    prefix = "_source_rowid INTEGER, _archived_at TEXT, _archive_run_id TEXT," if archive else ""
    con.execute(
        f"""
        CREATE TABLE bar_pattern_features (
            {prefix}
            symbol TEXT,
            bar_timestamp TEXT,
            timeframe TEXT,
            feature_version TEXT,
            close REAL,
            volume REAL,
            triple_barrier_label INTEGER,
            trend_scan_label INTEGER
        )
        """
    )


def test_historical_bar_training_reads_hot_and_archive_stores():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        hot = base / "trades.db"
        archive = base / "historical_bars.db"
        with sqlite3.connect(hot) as con:
            _create_bar_table(con)
            con.execute(
                """
                INSERT INTO bar_pattern_features (
                    symbol, bar_timestamp, timeframe, feature_version, close,
                    volume, triple_barrier_label, trend_scan_label
                ) VALUES ('MSFT', '2026-06-11T14:30:00+00:00', '1m', 'v4', 2, 200, 0, 0)
                """
            )
        with sqlite3.connect(archive) as con:
            _create_bar_table(con, archive=True)
            con.execute(
                """
                INSERT INTO bar_pattern_features (
                    _source_rowid, _archived_at, _archive_run_id,
                    symbol, bar_timestamp, timeframe, feature_version, close,
                    volume, triple_barrier_label, trend_scan_label
                ) VALUES (
                    1, '2026-06-12T00:00:00+00:00', 'test',
                    'AAPL', '2026-06-01T14:30:00+00:00', '1m', 'v4', 1, 100, 1, 1
                )
                """
            )
        rows = fetch_historical_bar_training_rows(
            db_path=hot,
            archive_db_path=archive,
            start_date="2026-06-01",
            end_date="2026-06-12",
            label_target="triple_barrier_label",
            limit=10,
            rows_per_symbol=0,
        )
        assert [row["symbol"] for row in rows] == ["AAPL", "MSFT"]
        assert [row["triple_barrier_label"] for row in rows] == [1, 0]


if __name__ == "__main__":
    test_historical_bar_training_reads_hot_and_archive_stores()
    print("[OK] historical bar training archive read tests passed")
