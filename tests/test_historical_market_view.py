#!/usr/bin/env python3
"""Tests for historical candle research coverage/audit tooling."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from services.bar_pattern_feature_service import BAR_PATTERN_FEATURE_VERSION

from scripts.historical_market_view import (
    build_historical_market_view_payload,
    rows_to_edge_rows,
    write_flat_csv,
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
                day_of_week INTEGER,
                minute_of_day INTEGER,
                ema_12 REAL,
                ema_26 REAL,
                ema_200 REAL,
                price_vs_ema_200_pct REAL,
                macd REAL,
                macd_signal REAL,
                macd_histogram REAL,
                rsi_14 REAL,
                candle_body_pct REAL,
                close_location REAL,
                range_atr_ratio REAL,
                volume_ratio_20 REAL,
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
        rows = []
        for idx in range(60):
            label = 1 if idx >= 30 else -1
            symbol = "AAPL" if idx % 2 == 0 else "MSFT"
            market_date = "2026-06-10" if idx < 30 else "2026-06-11"
            rows.append(
                (
                    symbol,
                    f"{market_date}T14:{idx % 60:02d}:00+00:00",
                    "1m",
                    BAR_PATTERN_FEATURE_VERSION,
                    100 + idx,
                    101 + idx,
                    99 + idx,
                    100.5 + idx,
                    1000 + idx,
                    100.4 + idx,
                    idx % 5,
                    14 * 60 + idx,
                    100 + idx,
                    99 + idx,
                    98 + idx,
                    float(idx),
                    idx / 10,
                    idx / 12,
                    idx / 20,
                    30 + idx,
                    idx / 100,
                    idx / 60,
                    1 + idx / 100,
                    1 + idx / 50,
                    label,
                    2.0,
                    8,
                    0.5 if label > 0 else -0.4,
                    "constructive_continuation" if label > 0 else "bearish_distribution",
                    float(idx),
                    "long_candidate" if label > 0 else "avoid",
                    "good" if label > 0 else "weak",
                    float(idx),
                    100.0 - idx,
                    label,
                    "profit_target_first" if label > 0 else "stop_loss_first",
                    4,
                    0.5,
                    0.4,
                )
            )
        con.executemany(
            """
            INSERT INTO bar_pattern_features VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            rows,
        )


def test_rows_to_edge_rows_uses_forward_target_and_features():
    rows = [
        {
            "symbol": "AAPL",
            "bar_timestamp": "2026-06-10T14:30:00+00:00",
            "trend_scan_return_pct": 0.7,
            "trend_scan_label": 1,
            "pattern_score": 72,
            "rsi_14": 64,
            "pattern_label": "constructive",
        }
    ]

    edge_rows = rows_to_edge_rows(rows, target="trend_scan_return_pct")

    assert len(edge_rows) == 1
    assert edge_rows[0].forward_return_pct == 0.7
    assert edge_rows[0].numeric_features["rsi_14"] == 64
    assert "trend_scan_return_pct" not in edge_rows[0].numeric_features
    assert edge_rows[0].categorical_features["pattern_label"] == "constructive"


def test_historical_market_view_payload_and_flat_export(tmp_path):
    db_path = tmp_path / "trades.db"
    _build_db(db_path)

    payload, rows = build_historical_market_view_payload(
        db_path=db_path,
        archive_db_path=None,
        start_date="2026-06-10",
        end_date="2026-06-11",
        target="trend_scan_return_pct",
        feature_min_rows=30,
        feature_permutations=20,
    )
    csv_path = write_flat_csv(rows, tmp_path / "flat.csv")

    assert payload["runtime_effect"] == "read_only_research_no_live_authority"
    assert payload["coverage"]["labeled_rows"] == 60
    assert payload["coverage"]["symbols"] == 2
    assert payload["coverage"]["market_dates"] == 2
    assert payload["overall_baseline"]["n"] == 60
    assert payload["baselines"]["trend_scan_label"][0]["n"] == 30
    assert payload["feature_scan"]
    assert csv_path.exists()
    with csv_path.open() as fh:
        exported = list(csv.DictReader(fh))
    assert len(exported) == 60
    assert exported[0]["symbol"] in {"AAPL", "MSFT"}
