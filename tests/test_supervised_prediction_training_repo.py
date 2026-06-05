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
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                candle_body_pct REAL,
                close_location REAL,
                range_atr_ratio REAL,
                volume_weighted_pressure_3 REAL,
                volume_delta REAL,
                institutional_volume_delta REAL,
                cumulative_volume_delta REAL,
                cvd_price_corr_20 REAL,
                vpin_toxicity_20 REAL,
                fractional_diff_close_045 REAL,
                fractional_diff_zscore_20 REAL,
                trend_scan_label INTEGER,
                trend_scan_tstat REAL,
                trend_scan_bars INTEGER,
                trend_scan_return_pct REAL,
                pattern_label TEXT,
                pattern_score REAL,
                opportunity_action TEXT,
                opportunity_quality TEXT,
                long_opportunity_score REAL,
                sell_opportunity_score REAL,
                triple_barrier_label INTEGER,
                triple_barrier_reason TEXT,
                triple_barrier_bars_to_event INTEGER,
                triple_barrier_profit_pct REAL,
                triple_barrier_stop_pct REAL
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
                (idx, f"2026-06-03T0{idx}:00:08+00:00", available_at),
            )
            con.execute(
                """
                INSERT INTO labeled_setups (
                    snapshot_id, ret_fwd_5m, ret_fwd_15m, ret_fwd_30m
                ) VALUES (?, 0.1, 0.2, 0.3)
                """,
                (idx,),
            )
            con.execute(
                """
                INSERT INTO bar_pattern_features (
                    symbol, bar_timestamp, timeframe,
                    candle_body_pct, close_location, range_atr_ratio,
                    volume_weighted_pressure_3,
                    volume_delta, institutional_volume_delta,
                    cumulative_volume_delta, cvd_price_corr_20,
                    vpin_toxicity_20, fractional_diff_close_045,
                    fractional_diff_zscore_20, trend_scan_label,
                    trend_scan_tstat, trend_scan_bars, trend_scan_return_pct,
                    pattern_label, pattern_score,
                    opportunity_action, opportunity_quality,
                    long_opportunity_score, sell_opportunity_score,
                    triple_barrier_label, triple_barrier_reason,
                    triple_barrier_bars_to_event, triple_barrier_profit_pct,
                    triple_barrier_stop_pct
                ) VALUES (
                    'AAPL', ?, '1m',
                    0.6, 0.8, 1.2,
                    0.3,
                    1200, 1200, 3600, 0.42,
                    0.74, 12.3, 1.1, 1,
                    2.8, 8, 0.9,
                    'constructive_force_pvt', 72,
                    'long_candidate', 'good_buy_window',
                    80, 20,
                    1, 'profit_target_first',
                    4, 0.5, 0.3
                )
                """,
                (f"2026-06-03T0{idx}:00:00+00:00",),
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
    assert rows[0]["timestamp"] == "2026-06-03T01:00:08+00:00"
    assert rows[0]["candle_body_pct"] == 0.6
    assert rows[0]["cvd_price_corr_20"] == 0.42
    assert rows[0]["trend_scan_label"] == 1
    assert rows[0]["triple_barrier_label"] == 1


if __name__ == "__main__":
    tests = [test_fetch_training_rows_respects_feature_available_at_cutoff]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} supervised prediction training repo tests passed.")
