#!/usr/bin/env python3
"""Tests for historical-bar validation bucket reporting."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.bar_pattern_feature_service import BAR_PATTERN_FEATURE_VERSION  # noqa: E402
from services.ops_checks.historical_bar_validation_checks import (  # noqa: E402
    build_historical_bar_validation_payload,
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
                minute_of_day INTEGER,
                rolling_volatility_20_pct REAL,
                cvd_price_corr_20 REAL,
                vpin_toxicity_20 REAL,
                fractional_diff_zscore_20 REAL,
                triple_barrier_label INTEGER
            )
            """
        )
        rows = []
        for idx in range(80):
            rows.append(
                (
                    "AAPL" if idx < 40 else "MSFT",
                    f"2026-01-02T14:{idx % 60:02d}:00+00:00",
                    "1m",
                    BAR_PATTERN_FEATURE_VERSION,
                    570 + idx,
                    0.03 if idx < 20 else 0.30,
                    -0.2 if idx < 20 else 0.5,
                    0.1 if idx < 20 else 0.8,
                    -1.5 if idx < 20 else 1.5,
                    1 if idx % 2 else -1,
                )
            )
        con.executemany(
            "INSERT INTO bar_pattern_features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def test_historical_bar_validation_payload_builds_buckets():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        _build_db(db_path)
        payload = build_historical_bar_validation_payload(
            db_path=db_path,
            start_date="2026-01-01",
            end_date="2026-01-03",
            label_target="triple_barrier_label",
            rows_per_symbol=50,
            limit=100,
            min_bucket_rows=10,
        )

    assert payload["report_version"] == "historical_bar_validation_buckets_v1"
    assert payload["rows_loaded"] == 80
    families = {row["bucket_family"] for row in payload["bucket_rows"]}
    assert "symbol" in families
    assert "session_phase" in families
    assert "volatility" in families


if __name__ == "__main__":
    test_historical_bar_validation_payload_builds_buckets()
    print("[OK] test_historical_bar_validation_payload_builds_buckets")
