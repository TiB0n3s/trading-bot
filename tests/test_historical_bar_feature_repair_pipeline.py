#!/usr/bin/env python3
"""Tests for replaying cached historical bars into an isolated feature DB."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline.historical_bar_feature_repair import main


def _write_cache_chunk(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 6, 10, 13, 30, tzinfo=timezone.utc)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "Timestamp",
                "IntervalStart",
                "IntervalSemantics",
                "Symbol",
                "Source",
                "Adjusted",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
                "VWAP",
            ],
        )
        writer.writeheader()
        for idx in range(35):
            ts = (start + timedelta(minutes=idx)).isoformat()
            writer.writerow(
                {
                    "Timestamp": ts,
                    "IntervalStart": ts,
                    "IntervalSemantics": "inclusive_start_regular_hours_1m",
                    "Symbol": "AAPL",
                    "Source": "test_cache",
                    "Adjusted": "True",
                    "Open": 100 + idx * 0.1,
                    "High": 100.2 + idx * 0.1,
                    "Low": 99.8 + idx * 0.1,
                    "Close": 100.1 + idx * 0.1,
                    "Volume": 1000 + idx,
                    "VWAP": 100.05 + idx * 0.1,
                }
            )


def test_feature_repair_can_target_isolated_db(tmp_path):
    cache_dir = tmp_path / "cache"
    db_path = tmp_path / "research_features.db"
    _write_cache_chunk(cache_dir / "AAPL_1min_rth_2026-06-10_2026-06-10.csv")

    rc = main(
        [
            "--start-date",
            "2026-06-10",
            "--end-date",
            "2026-06-10",
            "--symbol",
            "AAPL",
            "--cache-dir",
            str(cache_dir),
            "--db-path",
            str(db_path),
        ]
    )

    assert rc == 0
    with sqlite3.connect(db_path) as con:
        count = con.execute("SELECT COUNT(*) FROM bar_pattern_features").fetchone()[0]
        assert count > 0
