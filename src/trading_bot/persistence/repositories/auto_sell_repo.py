"""Repository helpers for first-class auto-sell candidate persistence."""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection


def init_tables(db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_sell_candidates (
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
                sell_pressure_score REAL,
                sell_pressure_recommendation TEXT,
                sell_pressure_reason TEXT,
                layered_ml_available INTEGER DEFAULT 0,
                layered_ml_final_instruction TEXT,
                layered_ml_master_confidence_score REAL,
                layered_ml_ensemble_probability_pct REAL,
                layered_ml_reason TEXT,
                auto_sell_enabled INTEGER DEFAULT 0,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_sell_candidates_timestamp
            ON auto_sell_candidates(timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_sell_candidates_symbol_time
            ON auto_sell_candidates(symbol, timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_sell_candidates_date_action
            ON auto_sell_candidates(substr(timestamp, 1, 10), action, order_submitted)
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_sell_decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                candidate_timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT,
                severity TEXT,
                reason TEXT,
                auto_sell_enabled INTEGER DEFAULT 0,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT,
                order_status TEXT,
                candidate_json TEXT,
                order_json TEXT,
                runtime_effect TEXT NOT NULL DEFAULT 'auto_sell_paper_execution_path'
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_sell_snapshots_time
            ON auto_sell_decision_snapshots(candidate_timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_sell_snapshots_symbol_time
            ON auto_sell_decision_snapshots(symbol, candidate_timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_sell_snapshots_date
            ON auto_sell_decision_snapshots(substr(candidate_timestamp, 1, 10))
            """
        )


def table_exists(table_name: str, db_path=DB_PATH) -> bool:
    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    return row is not None


def table_columns(table_name: str, db_path=DB_PATH) -> set[str]:
    with get_connection(db_path) as con:
        rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def insert_candidate_and_snapshot(
    *,
    timestamp: str,
    created_at: str,
    position: Any,
    session: dict[str, Any],
    decision: dict[str, Any],
    auto_sell_enabled: bool,
    order: dict[str, Any],
    candidate_json: str,
    order_json: str,
    db_path=DB_PATH,
) -> None:
    init_tables(db_path=db_path)
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO auto_sell_candidates (
                timestamp, symbol, qty, action, severity, reason,
                trend_label, trend_score, session_return_pct,
                momentum_5m_pct, momentum_15m_pct, momentum_30m_pct,
                distance_from_vwap_pct, unrealized_pl, unrealized_plpc,
                sell_pressure_score, sell_pressure_recommendation, sell_pressure_reason,
                layered_ml_available, layered_ml_final_instruction,
                layered_ml_master_confidence_score,
                layered_ml_ensemble_probability_pct, layered_ml_reason,
                auto_sell_enabled, order_submitted, order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                getattr(position, "symbol", None),
                _float(getattr(position, "qty", None)),
                decision.get("action"),
                decision.get("severity"),
                decision.get("reason"),
                session.get("trend_label"),
                session.get("trend_score"),
                session.get("session_return_pct"),
                session.get("momentum_5m_pct"),
                session.get("momentum_15m_pct"),
                session.get("momentum_30m_pct"),
                session.get("distance_from_vwap_pct"),
                _float(getattr(position, "unrealized_pl", None)),
                (_float(getattr(position, "unrealized_plpc", None)) or 0.0) * 100.0,
                decision.get("sell_pressure_score"),
                decision.get("sell_pressure_recommendation"),
                decision.get("sell_pressure_reason"),
                1 if decision.get("layered_ml_available") else 0,
                decision.get("layered_ml_final_instruction"),
                decision.get("layered_ml_master_confidence_score"),
                decision.get("layered_ml_ensemble_probability_pct"),
                decision.get("layered_ml_reason"),
                1 if auto_sell_enabled else 0,
                1 if order else 0,
                order.get("order_id") if isinstance(order, dict) else None,
            ),
        )
        con.execute(
            """
            INSERT INTO auto_sell_decision_snapshots (
                created_at, candidate_timestamp, symbol, action, severity, reason,
                auto_sell_enabled, order_submitted, order_id, order_status,
                candidate_json, order_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                timestamp,
                getattr(position, "symbol", None),
                decision.get("action"),
                decision.get("severity"),
                decision.get("reason"),
                1 if auto_sell_enabled else 0,
                1 if order else 0,
                order.get("order_id") if isinstance(order, dict) else None,
                order.get("status") if isinstance(order, dict) else None,
                candidate_json,
                order_json,
            ),
        )


def candidate_action_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT action, severity, COUNT(*) AS n,
                   AVG(unrealized_plpc) AS avg_plpc,
                   AVG(layered_ml_master_confidence_score) AS avg_ml_confidence,
                   SUM(CASE WHEN order_submitted = 1 THEN 1 ELSE 0 END) AS submitted
            FROM auto_sell_candidates
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY action, severity
            ORDER BY n DESC, action, severity
            """,
            (target_date,),
        ).fetchall()


def top_candidate_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT timestamp, symbol, action, severity, unrealized_plpc,
                   sell_pressure_score, layered_ml_master_confidence_score,
                   layered_ml_ensemble_probability_pct, order_submitted, order_id, reason
            FROM auto_sell_candidates
            WHERE substr(timestamp, 1, 10) = ?
            ORDER BY
                CASE WHEN action = 'sell_candidate' THEN 0 ELSE 1 END,
                COALESCE(layered_ml_master_confidence_score, 0) DESC,
                COALESCE(sell_pressure_score, 0) DESC,
                id DESC
            LIMIT 15
            """,
            (target_date,),
        ).fetchall()


def decision_snapshot_summary(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT COUNT(*) AS n,
                   SUM(CASE WHEN order_submitted = 1 THEN 1 ELSE 0 END) AS submitted,
                   SUM(CASE
                       WHEN json_extract(candidate_json, '$.layered_ml_available')
                            IN (1, '1', 'true', 'True')
                       THEN 1 ELSE 0 END
                   ) AS layered_rows
            FROM auto_sell_decision_snapshots
            WHERE substr(candidate_timestamp, 1, 10) = ?
            """,
            (target_date,),
        ).fetchone()


def layered_ml_summary(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                COALESCE(layered_ml_final_instruction, 'unknown') AS instruction,
                COUNT(*) AS n,
                AVG(layered_ml_master_confidence_score) AS avg_master,
                AVG(layered_ml_ensemble_probability_pct) AS avg_ensemble,
                SUM(CASE WHEN action = 'sell_candidate' THEN 1 ELSE 0 END) AS sell_candidates
            FROM auto_sell_candidates
            WHERE substr(timestamp, 1, 10) = ?
              AND layered_ml_available = 1
            GROUP BY layered_ml_final_instruction
            ORDER BY n DESC, instruction
            """,
            (target_date,),
        ).fetchall()


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None
