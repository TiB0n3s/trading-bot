#!/usr/bin/env python3
"""Staged observe-only integration tests for the ML platform."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ml_platform.staged import STAGED_STATUS, staged_ml_integration_report


def create_fixture_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            CREATE TABLE feature_snapshots (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                last_price REAL,
                ret_1m REAL,
                ret_5m REAL,
                ret_15m REAL,
                range_pos_15m REAL,
                distance_from_5m_high REAL,
                distance_from_5m_low REAL,
                distance_from_vwap REAL,
                volume_ratio_5m REAL,
                benchmark_symbol TEXT,
                benchmark_ret_5m REAL,
                relative_strength_5m REAL,
                spread_pct REAL,
                market_session TEXT,
                macro_regime TEXT,
                market_bias TEXT,
                trend_direction TEXT,
                trend_strength TEXT,
                bar_timeframe TEXT,
                bar_count INTEGER,
                setup_label TEXT,
                setup_recommendation TEXT,
                setup_score REAL,
                setup_confidence TEXT,
                setup_key TEXT
            );

            CREATE TABLE labeled_setups (
                snapshot_id INTEGER,
                timestamp TEXT,
                future_price_5m REAL,
                future_price_15m REAL,
                future_price_30m REAL,
                ret_fwd_5m REAL,
                ret_fwd_15m REAL,
                ret_fwd_30m REAL,
                max_up_15m REAL,
                max_down_15m REAL,
                outcome_label TEXT
            );

            CREATE TABLE daily_symbol_context (
                market_date TEXT,
                symbol TEXT,
                bias TEXT,
                confidence TEXT,
                risk_level TEXT,
                entry_quality TEXT,
                catalyst_score REAL,
                relative_strength_score REAL,
                sector_alignment TEXT,
                index_alignment TEXT
            );

            CREATE TABLE daily_symbol_events (
                market_date TEXT,
                symbol TEXT,
                event_type TEXT
            );

            CREATE TABLE daily_symbol_predictions (
                market_date TEXT,
                symbol TEXT,
                prediction_score REAL,
                probability_of_profit REAL,
                probability_of_order REAL,
                expected_pnl REAL,
                confidence TEXT,
                sample_size INTEGER,
                trend_label TEXT,
                timing_score REAL,
                reason TEXT
            );
            """
        )
        con.execute(
            """
            INSERT INTO feature_snapshots (
                id, timestamp, symbol, last_price, ret_1m, ret_5m, ret_15m,
                range_pos_15m, distance_from_5m_high, distance_from_5m_low,
                distance_from_vwap, volume_ratio_5m, benchmark_symbol,
                benchmark_ret_5m, relative_strength_5m, spread_pct,
                market_session, macro_regime, market_bias, trend_direction,
                trend_strength, bar_timeframe, bar_count, setup_label,
                setup_recommendation, setup_score, setup_confidence, setup_key
            ) VALUES (
                1, '2026-05-26T14:35:00Z', 'AAPL', 200.0, 0.1, 0.2, 0.3,
                0.55, -0.1, 0.2, 0.02, 1.4, 'QQQ', 0.1, -0.35, 0.03,
                'open', 'caution', 'buy', 'neutral', 'weak', '1m', 20,
                NULL, NULL, NULL, NULL, NULL
            )
            """
        )
        con.execute(
            """
            INSERT INTO labeled_setups (
                snapshot_id, timestamp, future_price_5m, future_price_15m,
                future_price_30m, ret_fwd_5m, ret_fwd_15m, ret_fwd_30m,
                max_up_15m, max_down_15m, outcome_label
            ) VALUES (
                1, '2026-05-26T14:35:00Z', 200.4, 201.0, 201.2,
                0.2, 0.5, 0.6, 0.7, -0.1, 'favorable'
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_symbol_context VALUES (
                '2026-05-26', 'AAPL', 'buy', 'medium', 'medium',
                'good_on_pullbacks', 4, 6, 'mixed', 'aligned'
            )
            """
        )
        con.execute(
            "INSERT INTO daily_symbol_events VALUES ('2026-05-26', 'AAPL', 'analyst_note')"
        )
        con.execute(
            """
            INSERT INTO daily_symbol_predictions VALUES (
                '2026-05-26', 'AAPL', 0.62, 0.58, 0.40, 0.12,
                'medium', 25, 'constructive', 0.7, 'fixture prediction'
            )
            """
        )


def with_fixture_db(fn):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "fixture.db"
        create_fixture_db(db_path)
        fn(db_path)


def test_staged_report_composes_observe_only_contracts():
    def run(db_path: Path):
        report = staged_ml_integration_report(
            db_path=db_path,
            start_date="2026-05-26",
            end_date="2026-05-26",
            candidate_model="similarity_v0",
            prediction_symbol="AAPL",
        )

        assert report["status"] == STAGED_STATUS
        assert report["runtime_effect"] == "none"
        assert report["dataset_profile"]["tables"]["feature_snapshots"] == 1
        assert report["dataset_manifest"]["row_count"] == 1
        assert report["brain_feature_manifest"]["rows"] == 1
        assert report["brain_feature_manifest"]["runtime_use"] == "none"
        assert report["replay_contract"]["status"] == "complete"
        assert "No orders, risk controls, or live decisions were changed" in report["replay_contract"]["note"]
        assert report["prediction_provider_contract"]["runtime_effect"] == "none"
        assert report["prediction_provider_contract"]["sample_prediction"]["runtime_effect"] == "none"
        assert report["retraining_readiness"]["runtime_effect"] == "none"
        assert report["retraining_readiness"]["promotion_allowed"] is False
        assert "fewer_than_500_feature_snapshots" in report["retraining_readiness"]["current_evidence"]["blockers"]
        assert report["promotion_gates"]["requires_no_broker_or_order_side_effects"] is True

    with_fixture_db(run)


def test_staged_readiness_cli_writes_report():
    def run(db_path: Path):
        output = db_path.with_suffix(".staged.json")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ml_platform.cli",
                "staged-readiness",
                "--db-path",
                str(db_path),
                "--start-date",
                "2026-05-26",
                "--end-date",
                "2026-05-26",
                "--candidate-model",
                "similarity_v0",
                "--prediction-symbol",
                "AAPL",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        assert output.exists()
        assert '"status": "staged_observe_only_no_runtime_effect"' in output.read_text()

    with_fixture_db(run)


def test_retraining_readiness_cli_blocks_placeholder_data():
    def run(db_path: Path):
        output = db_path.with_suffix(".readiness.json")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ml_platform.cli",
                "retraining-readiness",
                "--db-path",
                str(db_path),
                "--start-date",
                "2026-05-26",
                "--end-date",
                "2026-05-26",
                "--trading-sessions-observed",
                "1",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        data = json.loads(output.read_text())
        assert data["runtime_effect"] == "none"
        assert data["promotion_allowed"] is False
        assert "fewer_than_20_trading_sessions_observed" in data["current_evidence"]["blockers"]

    with_fixture_db(run)


def test_similarity_v0_metadata_is_research_only():
    model_card = json.loads((ROOT / "ml/models/similarity_v0/model_card.json").read_text())
    metrics = json.loads((ROOT / "ml/models/similarity_v0/metrics.placeholder.json").read_text())

    assert model_card["model_id"] == "similarity_v0"
    assert model_card["status"] == "research"
    assert model_card["runtime_effect"] == "none"
    assert model_card["promotion_allowed"] is False
    assert model_card["artifact_path"] is None
    assert metrics["status"] == "not_run"
    assert metrics["promotion_allowed"] is False


if __name__ == "__main__":
    test_staged_report_composes_observe_only_contracts()
    print("[OK] test_staged_report_composes_observe_only_contracts")
    test_staged_readiness_cli_writes_report()
    print("[OK] test_staged_readiness_cli_writes_report")
    test_retraining_readiness_cli_blocks_placeholder_data()
    print("[OK] test_retraining_readiness_cli_blocks_placeholder_data")
    test_similarity_v0_metadata_is_research_only()
    print("[OK] test_similarity_v0_metadata_is_research_only")
    print("\nAll 4 staged ML platform tests passed.")
