#!/usr/bin/env python3
"""Tests for derived bar entry/exit timing quality labels."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from repositories.bar_timing_quality_repo import BarTimingQualityRepository
from services.bar_timing_quality_service import (
    BAR_TIMING_QUALITY_LABEL_VERSION,
    BarTimingQualityService,
)


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                bar_source TEXT,
                feature_version TEXT,
                forward_return_pct REAL,
                forward_mfe_pct REAL,
                forward_mae_pct REAL,
                long_opportunity_score REAL,
                sell_opportunity_score REAL,
                horizon_bars INTEGER,
                pattern_label TEXT,
                opportunity_action TEXT,
                opportunity_quality TEXT,
                triple_barrier_label INTEGER,
                trend_scan_label INTEGER,
                trend_scan_tstat REAL,
                feature_json TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO bar_pattern_features (
                symbol, bar_timestamp, timeframe, bar_source, feature_version,
                forward_return_pct, forward_mfe_pct, forward_mae_pct,
                long_opportunity_score, sell_opportunity_score, horizon_bars,
                pattern_label, opportunity_action, opportunity_quality,
                triple_barrier_label, trend_scan_label, trend_scan_tstat, feature_json
            ) VALUES (?, ?, '1m', ?, 'test_features_v1', ?, ?, ?, ?, ?, 60, ?, ?, ?, ?, ?, ?, '{}')
            """,
            [
                (
                    "AAPL",
                    "2026-06-12T14:30:00+00:00",
                    "historical_bar_archive",
                    0.85,
                    1.45,
                    -0.20,
                    86,
                    18,
                    "trend_continuation",
                    "long_candidate",
                    "best_buy_window",
                    1,
                    1,
                    3.2,
                ),
                (
                    "AAPL",
                    "2026-06-12T15:30:00+00:00",
                    "session_momentum_market_data",
                    -0.65,
                    0.12,
                    -1.35,
                    22,
                    84,
                    "distribution",
                    "sell_candidate",
                    "exit_window",
                    -1,
                    -1,
                    -2.8,
                ),
            ],
        )


def test_classifies_best_entry_and_best_exit_rows():
    repo = BarTimingQualityRepository()
    service = BarTimingQualityService(repository=repo)

    best_entry = service.classify_row(
        {
            "bar_pattern_feature_id": 1,
            "symbol": "AAPL",
            "bar_timestamp": "2026-06-12T14:30:00+00:00",
            "timeframe": "1m",
            "bar_source": "historical",
            "feature_version": "test",
            "forward_return_pct": 0.85,
            "forward_mfe_pct": 1.45,
            "forward_mae_pct": -0.2,
            "long_opportunity_score": 86,
            "sell_opportunity_score": 18,
            "horizon_bars": 60,
            "trend_scan_tstat": 3.2,
        }
    )
    best_exit = service.classify_row(
        {
            "bar_pattern_feature_id": 2,
            "symbol": "AAPL",
            "bar_timestamp": "2026-06-12T15:30:00+00:00",
            "timeframe": "1m",
            "bar_source": "live",
            "feature_version": "test",
            "forward_return_pct": -0.65,
            "forward_mfe_pct": 0.12,
            "forward_mae_pct": -1.35,
            "long_opportunity_score": 22,
            "sell_opportunity_score": 84,
            "horizon_bars": 60,
            "trend_scan_tstat": -2.8,
        }
    )

    assert best_entry["entry_timing_label"] == "best_entry"
    assert best_entry["exit_timing_label"] == "hold_preferred"
    assert best_exit["entry_timing_label"] == "avoid_entry"
    assert best_exit["exit_timing_label"] == "best_exit"


def test_materialize_persists_labels_for_historical_and_live_bar_sources():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        _build_db(db_path)
        service = BarTimingQualityService(repository=BarTimingQualityRepository(db_path=db_path))
        result = service.materialize(target_date="2026-06-12")
        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                SELECT symbol, bar_source, entry_timing_label, exit_timing_label, label_version
                FROM bar_timing_quality_labels
                ORDER BY bar_timestamp
                """
            ).fetchall()

    assert result["source_rows"] == 2
    assert result["rows_written"] == 2
    assert [row["bar_source"] for row in rows] == [
        "historical_bar_archive",
        "session_momentum_market_data",
    ]
    assert rows[0]["entry_timing_label"] == "best_entry"
    assert rows[1]["exit_timing_label"] == "best_exit"
    assert rows[0]["label_version"] == BAR_TIMING_QUALITY_LABEL_VERSION


if __name__ == "__main__":
    test_classifies_best_entry_and_best_exit_rows()
    print("[OK] test_classifies_best_entry_and_best_exit_rows")
    test_materialize_persists_labels_for_historical_and_live_bar_sources()
    print("[OK] test_materialize_persists_labels_for_historical_and_live_bar_sources")
