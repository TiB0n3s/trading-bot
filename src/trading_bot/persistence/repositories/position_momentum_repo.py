"""Repository for position momentum monitor persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from db import DB_PATH, get_connection


def init_checks_table(db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS position_momentum_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                qty REAL,
                action TEXT,
                severity TEXT,
                reason TEXT,
                trend_label TEXT,
                trend_score REAL,
                session_return_pct REAL,
                momentum_5m_pct REAL,
                momentum_15m_pct REAL,
                momentum_30m_pct REAL,
                distance_from_vwap_pct REAL,
                unrealized_pl REAL,
                unrealized_plpc REAL,
                auto_sell_enabled INTEGER DEFAULT 0,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT,
                sell_pressure_score REAL,
                sell_pressure_recommendation TEXT,
                sell_pressure_reason TEXT
            )
            """
        )

        existing_cols = {
            row["name"]
            for row in con.execute("PRAGMA table_info(position_momentum_checks)").fetchall()
        }
        for col_name, col_type in (
            ("sell_pressure_score", "REAL"),
            ("sell_pressure_recommendation", "TEXT"),
            ("sell_pressure_reason", "TEXT"),
        ):
            if col_name not in existing_cols:
                con.execute(
                    f"ALTER TABLE position_momentum_checks ADD COLUMN {col_name} {col_type}"
                )


def insert_check(
    *,
    timestamp: str,
    symbol: str | None,
    qty: float,
    action: str | None,
    severity: str | None,
    reason: str | None,
    session: dict[str, Any],
    unrealized_pl: float,
    unrealized_plpc: float,
    auto_sell_enabled: bool,
    order_submitted: bool,
    order_id: str | None,
    sell_pressure_score: Any,
    sell_pressure_recommendation: str | None,
    sell_pressure_reason: str | None,
    db_path=DB_PATH,
) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO position_momentum_checks (
                timestamp,
                symbol,
                qty,
                action,
                severity,
                reason,
                trend_label,
                trend_score,
                session_return_pct,
                momentum_5m_pct,
                momentum_15m_pct,
                momentum_30m_pct,
                distance_from_vwap_pct,
                unrealized_pl,
                unrealized_plpc,
                auto_sell_enabled,
                order_submitted,
                order_id,
                sell_pressure_score,
                sell_pressure_recommendation,
                sell_pressure_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                symbol,
                qty,
                action,
                severity,
                reason,
                session.get("trend_label"),
                session.get("trend_score"),
                session.get("session_return_pct"),
                session.get("momentum_5m_pct"),
                session.get("momentum_15m_pct"),
                session.get("momentum_30m_pct"),
                session.get("distance_from_vwap_pct"),
                unrealized_pl,
                unrealized_plpc,
                1 if auto_sell_enabled else 0,
                1 if order_submitted else 0,
                order_id,
                sell_pressure_score,
                sell_pressure_recommendation,
                sell_pressure_reason,
            ),
        )


def latest_approved_buy_timestamp(symbol: str, db_path=DB_PATH) -> str | None:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT timestamp
            FROM trades
            WHERE symbol = ?
              AND LOWER(action) = 'buy'
              AND approved = 1
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
    return row["timestamp"] if row else None


def init_actions_table(db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS position_momentum_actions (
                symbol TEXT PRIMARY KEY,
                last_action_time TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                order_id TEXT
            )
            """
        )


def max_unrealized_plpc_today(symbol: str, today: str | None = None, db_path=DB_PATH):
    today = today or datetime.now().strftime("%Y-%m-%d")
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT MAX(unrealized_plpc) AS max_plpc
            FROM position_momentum_checks
            WHERE symbol = ?
              AND timestamp LIKE ?
              AND unrealized_plpc IS NOT NULL
            """,
            (symbol, f"{today}%"),
        ).fetchone()
    return row["max_plpc"] if row else None


def latest_action_time(symbol: str, db_path=DB_PATH) -> str | None:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT last_action_time
            FROM position_momentum_actions
            WHERE symbol = ?
            """,
            (symbol,),
        ).fetchone()
    return row["last_action_time"] if row else None


def upsert_auto_sell_action(
    *,
    symbol: str,
    timestamp: str,
    reason: str,
    order_id: str | None,
    db_path=DB_PATH,
) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO position_momentum_actions (
                symbol,
                last_action_time,
                action,
                reason,
                order_id
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                last_action_time=excluded.last_action_time,
                action=excluded.action,
                reason=excluded.reason,
                order_id=excluded.order_id
            """,
            (
                symbol,
                timestamp,
                "auto_sell",
                reason,
                order_id,
            ),
        )
