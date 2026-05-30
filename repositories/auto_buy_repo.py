"""Repository helpers for auto-buy candidate persistence."""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection


def init_tables(db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_buy_candidates (
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
            CREATE INDEX IF NOT EXISTS idx_auto_buy_candidates_timestamp
            ON auto_buy_candidates(timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_candidates_symbol
            ON auto_buy_candidates(symbol, timestamp)
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_buy_decision_snapshots (
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
                order_json TEXT,
                runtime_effect TEXT NOT NULL DEFAULT 'auto_buy_paper_execution_path'
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_decision_snapshots_time
            ON auto_buy_decision_snapshots(candidate_timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_decision_snapshots_symbol_time
            ON auto_buy_decision_snapshots(symbol, candidate_timestamp)
            """
        )
        existing_cols = {
            row["name"]
            for row in con.execute("PRAGMA table_info(auto_buy_candidates)").fetchall()
        }
        if "hard_block_reason" not in existing_cols:
            con.execute("ALTER TABLE auto_buy_candidates ADD COLUMN hard_block_reason TEXT")


def latest_session(symbol: str, db_path=DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT * FROM session_momentum WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    return dict(row) if row else {}


def latest_feature(symbol: str, db_path=DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT *
            FROM feature_snapshots
            WHERE symbol = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
    return dict(row) if row else {}


def auto_buy_orders_today(today: str, db_path=DB_PATH) -> int:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
              AND order_submitted = 1
            """,
            (today,),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def latest_auto_buy_order(symbol: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT timestamp, order_id
            FROM auto_buy_candidates
            WHERE symbol = ?
              AND order_submitted = 1
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()


def app_buy_cooldown(symbol: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT last_order_time
            FROM cooldowns
            WHERE symbol = ?
              AND action = 'buy'
            """,
            (symbol.upper(),),
        ).fetchone()


def recent_sell(symbol: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT last_sell_time, last_sell_price
            FROM recent_sells
            WHERE symbol = ?
            """,
            (symbol.upper(),),
        ).fetchone()


def app_approved_buys_today(today: str, symbol: str, db_path=DB_PATH) -> int:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND symbol = ?
              AND action = 'buy'
              AND approved = 1
              AND order_id IS NOT NULL
            """,
            (today, symbol.upper()),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def strong_buy_signals_today(symbol: str, today: str, db_path=DB_PATH) -> int:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM auto_buy_candidates
            WHERE symbol = ?
              AND substr(timestamp, 1, 10) = ?
              AND decision = 'strong_buy_candidate'
              AND order_submitted = 1
            """,
            (symbol.upper(), today),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def write_app_buy_cooldown(symbol: str, timestamp: str, db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO cooldowns (symbol, action, last_order_time)
            VALUES (?, 'buy', ?)
            """,
            (symbol.upper(), timestamp),
        )


def insert_candidate_and_snapshot(
    *,
    timestamp: str,
    created_at: str,
    candidate: dict[str, Any],
    live_buy_enabled: bool,
    order: dict[str, Any],
    candidate_json: str,
    order_json: str,
    db_path=DB_PATH,
) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO auto_buy_candidates (
                timestamp, symbol, signal_source, decision, score, reason,
                market_bias, entry_quality, risk_level,
                session_trend_label, session_trend_score, session_return_pct,
                momentum_5m_pct, momentum_15m_pct, momentum_30m_pct,
                distance_from_vwap_pct,
                setup_label, setup_recommendation, setup_score,
                hard_block_reason,
                feature_snapshot_id, live_buy_enabled, order_submitted, order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                candidate.get("symbol"),
                candidate.get("signal_source"),
                candidate.get("decision"),
                candidate.get("score"),
                candidate.get("reason"),
                candidate.get("market_bias"),
                candidate.get("entry_quality"),
                candidate.get("risk_level"),
                candidate.get("session_trend_label"),
                candidate.get("session_trend_score"),
                candidate.get("session_return_pct"),
                candidate.get("momentum_5m_pct"),
                candidate.get("momentum_15m_pct"),
                candidate.get("momentum_30m_pct"),
                candidate.get("distance_from_vwap_pct"),
                candidate.get("setup_label"),
                candidate.get("setup_recommendation"),
                candidate.get("setup_score"),
                candidate.get("hard_block_reason"),
                candidate.get("feature_snapshot_id"),
                1 if live_buy_enabled else 0,
                1 if order else 0,
                order.get("order_id") if isinstance(order, dict) else None,
            ),
        )
        con.execute(
            """
            INSERT INTO auto_buy_decision_snapshots (
                created_at, candidate_timestamp, symbol, signal_source,
                decision, score, reason, hard_block_reason, live_buy_enabled,
                live_block_reason, risk_cross_check_reason, order_submitted,
                order_id, order_status, candidate_json, order_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                timestamp,
                candidate.get("symbol"),
                candidate.get("signal_source"),
                candidate.get("decision"),
                candidate.get("score"),
                candidate.get("reason"),
                candidate.get("hard_block_reason"),
                1 if live_buy_enabled else 0,
                candidate.get("live_block_reason"),
                candidate.get("risk_cross_check_reason"),
                1 if order else 0,
                order.get("order_id") if isinstance(order, dict) else None,
                order.get("status") if isinstance(order, dict) else None,
                candidate_json,
                order_json,
            ),
        )


def trade_order_exists(order_id: str, db_path=DB_PATH) -> bool:
    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT id FROM trades WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
    return bool(row)


def insert_auto_buy_trade(
    *,
    timestamp: str,
    candidate: dict[str, Any],
    order: dict[str, Any],
    qty: int | None,
    position_size_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    db_path=DB_PATH,
) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO trades (
                timestamp,
                symbol,
                action,
                signal_price,
                approved,
                rejection_reason,
                confidence,
                position_size_pct,
                stop_loss_pct,
                take_profit_pct,
                order_id,
                order_status,
                qty,
                fill_price,
                market_bias,
                risk_level,
                entry_quality,
                session_trend_label,
                session_trend_score,
                session_return_pct,
                session_momentum_5m_pct,
                session_momentum_15m_pct,
                session_momentum_30m_pct,
                session_distance_from_vwap_pct,
                setup_label,
                setup_policy_action,
                setup_policy_reason,
                buy_opportunity_score,
                buy_opportunity_recommendation,
                buy_opportunity_reason
            ) VALUES (?, ?, 'buy', ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                candidate.get("symbol"),
                order.get("current_price"),
                "auto_buy_manager: internal bar-derived buy submitted",
                "auto_buy_manager",
                position_size_pct,
                stop_loss_pct,
                take_profit_pct,
                order.get("order_id"),
                order.get("status") or "submitted",
                qty,
                candidate.get("market_bias"),
                candidate.get("risk_level"),
                candidate.get("entry_quality"),
                candidate.get("session_trend_label"),
                candidate.get("session_trend_score"),
                candidate.get("session_return_pct"),
                candidate.get("momentum_5m_pct"),
                candidate.get("momentum_15m_pct"),
                candidate.get("momentum_30m_pct"),
                candidate.get("distance_from_vwap_pct"),
                candidate.get("setup_label"),
                candidate.get("setup_recommendation"),
                candidate.get("reason"),
                candidate.get("score"),
                candidate.get("decision"),
                candidate.get("reason"),
            ),
        )
