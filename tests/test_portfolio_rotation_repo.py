#!/usr/bin/env python3
"""Tests for portfolio rotation read-model inputs."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.portfolio_rotation_repo import recent_buy_signals  # noqa: E402


def _db(tmp_path: Path) -> Path:
    db_path = tmp_path / "trades.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                signal_price REAL,
                approved INTEGER,
                rejection_reason TEXT,
                market_bias TEXT,
                market_bias_effective TEXT,
                fundamental_score REAL,
                risk_level TEXT,
                entry_quality TEXT,
                trend_direction TEXT,
                trend_strength TEXT,
                momentum_direction TEXT,
                momentum_pct REAL,
                session_trend_label TEXT,
                session_trend_score REAL,
                session_return_pct REAL,
                session_momentum_5m_pct REAL,
                session_momentum_15m_pct REAL,
                session_momentum_30m_pct REAL,
                session_distance_from_vwap_pct REAL,
                prediction_score REAL,
                prediction_decision TEXT,
                setup_label TEXT,
                setup_policy_action TEXT,
                setup_size_multiplier REAL,
                buy_opportunity_score REAL,
                buy_opportunity_recommendation TEXT,
                buy_opportunity_reason TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE auto_buy_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_source TEXT,
                decision TEXT,
                score REAL,
                reason TEXT,
                market_bias TEXT,
                entry_quality TEXT,
                risk_level TEXT,
                session_trend_label TEXT,
                session_trend_score REAL,
                session_return_pct REAL,
                momentum_5m_pct REAL,
                momentum_15m_pct REAL,
                momentum_30m_pct REAL,
                distance_from_vwap_pct REAL,
                setup_label TEXT,
                setup_recommendation TEXT,
                setup_score REAL,
                hard_block_reason TEXT,
                feature_snapshot_id INTEGER,
                live_buy_enabled INTEGER DEFAULT 0,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE auto_buy_decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                candidate_timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_source TEXT,
                decision TEXT,
                score REAL,
                reason TEXT,
                hard_block_reason TEXT,
                live_buy_enabled INTEGER,
                live_block_reason TEXT,
                risk_cross_check_reason TEXT,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT,
                order_status TEXT,
                candidate_json TEXT,
                order_json TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO auto_buy_candidates (
                timestamp, symbol, signal_source, decision, score, reason,
                market_bias, entry_quality, risk_level, session_trend_label,
                session_trend_score, session_return_pct, momentum_5m_pct,
                momentum_15m_pct, momentum_30m_pct, distance_from_vwap_pct,
                setup_label, setup_recommendation, setup_score, hard_block_reason,
                live_buy_enabled, order_submitted
            ) VALUES (
                '2026-06-09 10:00:00', 'AAPL', 'internal_bar_only',
                'strong_buy_candidate', 22.0, 'ml_supported_candidate',
                'buy', 'excellent', 'medium', 'strong_uptrend',
                8.0, 1.2, 0.4, 0.8, 1.1, -0.2,
                'confirmed_near_vwap_recovery', 'boost', 74.0, '',
                1, 0
            )
            """
        )
        con.execute(
            """
            INSERT INTO auto_buy_decision_snapshots (
                created_at, candidate_timestamp, symbol, signal_source,
                decision, score, reason, live_buy_enabled, live_block_reason,
                risk_cross_check_reason, order_submitted, candidate_json, order_json
            ) VALUES (
                '2026-06-09 10:00:01', '2026-06-09 10:00:00', 'AAPL',
                'internal_bar_only', 'strong_buy_candidate', 22.0,
                'ml_supported_candidate', 1, 'macro_position_limit: full',
                'risk_ok', 0,
                '{"ml_prediction_score": 61.5, "ml_prediction_decision": "pass"}',
                '{}'
            )
            """
        )
    return db_path


def test_recent_buy_signals_includes_internal_auto_buy_candidates(tmp_path):
    rows = recent_buy_signals("2026-06-09 09:30:00", limit=20, db_path=_db(tmp_path))

    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "AAPL"
    assert row["action"] == "buy"
    assert row["approved"] == 0
    assert row["rejection_reason"] == "macro_position_limit: full"
    assert row["buy_opportunity_score"] == 22.0
    assert row["buy_opportunity_recommendation"] == "strong_buy_candidate"
    assert row["prediction_score"] == 61.5
    assert row["prediction_decision"] == "pass"


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_recent_buy_signals_includes_internal_auto_buy_candidates(Path(tmp))
    print("[OK] test_recent_buy_signals_includes_internal_auto_buy_candidates")
