#!/usr/bin/env python3
"""Tests for intraday trade-quality feedback."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.intraday_trade_feedback_service import IntradayTradeFeedbackService


def _create_trades_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            action TEXT,
            approved INTEGER,
            order_status TEXT,
            qty REAL,
            fill_price REAL,
            order_id TEXT,
            setup_label TEXT,
            setup_policy_action TEXT,
            ml_prediction_bucket TEXT,
            session_trend_label TEXT,
            session_return_pct REAL,
            buy_opportunity_recommendation TEXT,
            confidence TEXT,
            rejection_reason TEXT
        )
        """
    )


def _create_matched_trades_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE matched_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            entry_timestamp TEXT,
            exit_timestamp TEXT,
            holding_minutes REAL,
            qty REAL,
            entry_price REAL,
            exit_price REAL,
            realized_pnl_pct REAL,
            won INTEGER,
            setup_label TEXT,
            setup_policy_action TEXT,
            ml_prediction_bucket TEXT,
            session_trend_label TEXT,
            buy_opportunity_recommendation TEXT,
            entry_source TEXT,
            signal_source TEXT
        )
        """
    )


def _insert_matched_trade(
    con: sqlite3.Connection,
    *,
    entry_ts: str,
    exit_ts: str,
    symbol: str = "AAPL",
    pnl_pct: float = -0.5,
    setup_label: str = "near_vwap_neutral_fade_risk",
    setup_action: str = "avoid",
    ml_bucket: str = "weak_below_45",
) -> None:
    con.execute(
        """
        INSERT INTO matched_trades (
            symbol, entry_timestamp, exit_timestamp, holding_minutes, qty,
            entry_price, exit_price, realized_pnl_pct, won, setup_label,
            setup_policy_action, ml_prediction_bucket, session_trend_label,
            buy_opportunity_recommendation, entry_source, signal_source
        ) VALUES (?, ?, ?, 10, 1, 100, 99.5, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol,
            entry_ts,
            exit_ts,
            pnl_pct,
            1 if pnl_pct > 0 else 0,
            setup_label,
            setup_action,
            ml_bucket,
            "developing_uptrend",
            "strong_buy_candidate",
            "auto_buy_manager",
            "internal_bar_only",
        ),
    )


def _insert_trade(
    con: sqlite3.Connection,
    *,
    ts: str,
    symbol: str,
    action: str,
    qty: float,
    price: float,
    setup_action: str = "avoid",
    ml_bucket: str = "weak_below_45",
) -> None:
    con.execute(
        """
        INSERT INTO trades (
            timestamp, symbol, action, approved, order_status, qty, fill_price,
            order_id, setup_label, setup_policy_action, ml_prediction_bucket,
            session_trend_label, session_return_pct, buy_opportunity_recommendation,
            confidence, rejection_reason
        ) VALUES (?, ?, ?, 1, 'filled', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            symbol,
            action,
            qty,
            price,
            f"{symbol}-{action}-{ts}",
            "near_vwap_neutral_fade_risk",
            setup_action,
            ml_bucket,
            "developing_uptrend",
            1.2,
            "strong_buy_candidate",
            "auto_buy_manager",
            "auto_buy_manager: test",
        ),
    )


def test_intraday_feedback_blocks_repeated_losing_bucket():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        with sqlite3.connect(db_path) as con:
            _create_trades_table(con)
            for i, (buy, sell) in enumerate(((100, 99.5), (101, 100.4), (102, 101.2), (103, 102.1), (104, 103.2)), start=1):
                _insert_trade(
                    con,
                    ts=f"2026-06-04 10:0{i}:00",
                    symbol="AAPL",
                    action="buy",
                    qty=1,
                    price=buy,
                )
                _insert_trade(
                    con,
                    ts=f"2026-06-04 10:1{i}:00",
                    symbol="AAPL",
                    action="sell",
                    qty=1,
                    price=sell,
                )

        service = IntradayTradeFeedbackService(db_path=db_path)
        evidence = service.build_evidence("2026-06-04")
        decision = service.assess_candidate(
            target_date="2026-06-04",
            candidate={
                "setup_recommendation": "avoid",
                "setup_label": "near_vwap_neutral_fade_risk",
                "ml_prediction_bucket": "weak_below_45",
                "session_trend_label": "developing_uptrend",
            },
            evidence=evidence,
            allow_authority=True,
        )

        assert decision["status"] == "block"
        assert decision["score_penalty"] == -4.0
        assert "ml=weak_below_45|setup_action=avoid" in decision["hard_block_reason"]
        assert decision["evidence"]["trades"] == 5
        assert decision["evidence"]["losses"] == 5


def test_historical_feedback_blocks_repeated_losing_pattern_on_future_day():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        with sqlite3.connect(db_path) as con:
            _create_trades_table(con)
            _create_matched_trades_table(con)
            for i in range(1, 6):
                _insert_matched_trade(
                    con,
                    entry_ts=f"2026-06-03 10:0{i}:00",
                    exit_ts=f"2026-06-03 10:1{i}:00",
                )

        service = IntradayTradeFeedbackService(db_path=db_path)
        evidence = service.build_evidence("2026-06-04")
        decision = service.assess_candidate(
            target_date="2026-06-04",
            candidate={
                "setup_recommendation": "avoid",
                "setup_label": "near_vwap_neutral_fade_risk",
                "ml_prediction_bucket": "weak_below_45",
                "session_trend_label": "developing_uptrend",
            },
            evidence=evidence,
            allow_authority=True,
        )

        assert decision["status"] == "block"
        assert decision["evidence"]["same_day_trades"] == 0
        assert decision["evidence"]["historical_trades"] == 5
        assert decision["evidence"]["sources"] == ["historical_matched_trades"]


def test_intraday_feedback_is_observe_only_without_authority():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        with sqlite3.connect(db_path) as con:
            _create_trades_table(con)
            for i in range(1, 6):
                _insert_trade(
                    con,
                    ts=f"2026-06-04 10:0{i}:00",
                    symbol="AAPL",
                    action="buy",
                    qty=1,
                    price=100,
                )
                _insert_trade(
                    con,
                    ts=f"2026-06-04 10:1{i}:00",
                    symbol="AAPL",
                    action="sell",
                    qty=1,
                    price=99,
                )

        service = IntradayTradeFeedbackService(db_path=db_path)
        decision = service.assess_candidate(
            target_date="2026-06-04",
            candidate={
                "setup_recommendation": "avoid",
                "ml_prediction_bucket": "weak_below_45",
                "session_trend_label": "developing_uptrend",
            },
            allow_authority=False,
        )

    assert decision["status"] == "would_block"
    assert decision["runtime_effect"] == "observe_only_cash_mode_no_authority"


def test_broad_setup_action_only_penalizes_not_blocks():
    service = IntradayTradeFeedbackService()
    decision = service.assess_candidate(
        target_date="2026-06-04",
        candidate={
            "setup_recommendation": "watch",
            "ml_prediction_bucket": "high_55_plus",
            "session_trend_label": "strong_uptrend",
        },
        evidence={
            "setup_action=watch": {
                "key": "setup_action=watch",
                "trades": 5,
                "wins": 0,
                "losses": 5,
                "loss_rate": 1.0,
                "avg_pnl_pct": -0.3,
                "symbols": ["AAPL", "MRNA"],
            }
        },
        allow_authority=True,
    )

    assert decision["status"] == "penalty"
    assert decision["hard_block_reason"] is None


def test_intraday_performance_snapshot_summarizes_same_day_feedback():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        with sqlite3.connect(db_path) as con:
            _create_trades_table(con)
            _insert_trade(
                con,
                ts="2026-06-04 10:00:00",
                symbol="AAPL",
                action="buy",
                qty=1,
                price=100,
            )
            _insert_trade(
                con,
                ts="2026-06-04 10:12:00",
                symbol="AAPL",
                action="sell",
                qty=1,
                price=99,
            )

        service = IntradayTradeFeedbackService(db_path=db_path)
        snapshot = service.performance_snapshot("2026-06-04", phase="noon")

    assert snapshot["version"] == "intraday_learning_snapshot_v1"
    assert snapshot["phase"] == "noon"
    assert snapshot["same_day_closed_trades"] == 1
    assert snapshot["same_day_losses"] == 1
    assert snapshot["same_day_avg_pnl_pct"] == -1.0
    assert snapshot["evidence_keys"] > 0
    assert snapshot["top_feedback"]


def test_capture_intraday_performance_snapshot_persists_feedback_event():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        with sqlite3.connect(db_path) as con:
            _create_trades_table(con)
            _insert_trade(
                con,
                ts="2026-06-04 10:00:00",
                symbol="AAPL",
                action="buy",
                qty=1,
                price=100,
            )
            _insert_trade(
                con,
                ts="2026-06-04 10:12:00",
                symbol="AAPL",
                action="sell",
                qty=1,
                price=99,
            )

        service = IntradayTradeFeedbackService(db_path=db_path)
        snapshot = service.capture_performance_snapshot(
            "2026-06-04",
            phase="noon",
            trigger_symbol="AAPL",
        )

        with sqlite3.connect(db_path) as con:
            row = con.execute(
                """
                SELECT target_date, symbol, feedback_key, status, runtime_effect
                FROM auto_buy_intraday_feedback
                """
            ).fetchone()

    assert snapshot["trigger_symbol"] == "AAPL"
    assert row == (
        "2026-06-04",
        "AAPL",
        "intraday_performance_snapshot:noon:ml=weak_below_45|setup_action=avoid",
        "neutral",
        "paper_intraday_learning_feedback",
    )


def test_intraday_performance_snapshot_flags_short_hold_friction_pressure():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        with sqlite3.connect(db_path) as con:
            _create_trades_table(con)
            for idx, minute in enumerate((0, 10, 20), start=1):
                _insert_trade(
                    con,
                    ts=f"2026-06-04 10:{minute:02d}:00",
                    symbol="AAPL",
                    action="buy",
                    qty=1,
                    price=100 + idx,
                )
                _insert_trade(
                    con,
                    ts=f"2026-06-04 10:{minute + 3:02d}:00",
                    symbol="AAPL",
                    action="sell",
                    qty=1,
                    price=99 + idx,
                )

        service = IntradayTradeFeedbackService(db_path=db_path)
        snapshot = service.performance_snapshot("2026-06-04", phase="noon")

    friction = snapshot["execution_friction_memory"]
    assert friction["status"] == "short_hold_friction_pressure"
    assert friction["decision"] == "size_down"
    assert friction["short_hold_closed_trades"] == 3
    assert friction["short_hold_loss_rate"] == 1.0


def test_refresh_historical_outcome_feedback_persists_prior_sessions_for_active_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        with sqlite3.connect(db_path) as con:
            _create_trades_table(con)
            _create_matched_trades_table(con)
            for i in range(1, 4):
                _insert_matched_trade(
                    con,
                    entry_ts=f"2026-06-03 10:0{i}:00",
                    exit_ts=f"2026-06-03 10:1{i}:00",
                )

        service = IntradayTradeFeedbackService(db_path=db_path)
        payload = service.refresh_historical_outcome_feedback(
            "2026-06-04",
            created_at="2026-06-04T22:00:00+00:00",
        )
        evidence = service.build_evidence("2026-06-04")

        with sqlite3.connect(db_path) as con:
            rows = con.execute(
                """
                SELECT feedback_key, status, trades, evidence_json
                FROM auto_buy_historical_outcome_feedback
                WHERE target_date = '2026-06-04'
                """
            ).fetchall()

    assert payload["persisted_rows"] > 0
    assert rows
    persisted_keys = {row[0] for row in rows}
    assert "ml=weak_below_45|setup_action=avoid" in persisted_keys
    item = evidence["ml=weak_below_45|setup_action=avoid"]
    assert item["historical_materialized"] is True
    assert item["historical_trades"] == 3
    assert item["sources"] == ["historical_matched_trades"]


if __name__ == "__main__":
    test_intraday_feedback_blocks_repeated_losing_bucket()
    test_historical_feedback_blocks_repeated_losing_pattern_on_future_day()
    test_intraday_feedback_is_observe_only_without_authority()
    test_broad_setup_action_only_penalizes_not_blocks()
    test_intraday_performance_snapshot_summarizes_same_day_feedback()
    test_capture_intraday_performance_snapshot_persists_feedback_event()
    test_intraday_performance_snapshot_flags_short_hold_friction_pressure()
    test_refresh_historical_outcome_feedback_persists_prior_sessions_for_active_evidence()
    print("intraday trade feedback service tests passed")
