"""Repository helpers for remaining report and monitor scripts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection
from repositories.trade_accounting import fill_bearing_order_condition


class ReportingRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def table_exists(self, table: str) -> bool:
        with get_connection(self.db_path) as con:
            row = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
        return row is not None

    def table_columns(self, table: str) -> set[str]:
        if not self.table_exists(table):
            return set()
        with get_connection(self.db_path) as con:
            return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}

    def auto_buy_candidate_rows(self, target_date: str) -> list[Any]:
        if not self.table_exists("auto_buy_candidates") or not self.table_exists("feature_snapshots"):
            return []
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM auto_buy_candidates
                WHERE substr(timestamp, 1, 10) = ?
                ORDER BY timestamp, id
                """,
                (target_date,),
            ).fetchall()

    def feature_price_at_or_before(self, symbol: str, timestamp: str) -> tuple[float | None, str | None]:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT last_price, timestamp
                FROM feature_snapshots
                WHERE symbol = ?
                  AND julianday(timestamp) <= julianday(?)
                  AND last_price IS NOT NULL
                ORDER BY julianday(timestamp) DESC, id DESC
                LIMIT 1
                """,
                (symbol, timestamp),
            ).fetchone()
        if not row:
            return None, None
        return float(row["last_price"]), row["timestamp"]

    def feature_price_at_or_after(
        self,
        symbol: str,
        timestamp: str,
        minutes: int,
    ) -> tuple[float | None, str | None]:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT last_price, timestamp
                FROM feature_snapshots
                WHERE symbol = ?
                  AND julianday(timestamp) >= julianday(?, ?)
                  AND last_price IS NOT NULL
                ORDER BY julianday(timestamp) ASC, id ASC
                LIMIT 1
                """,
                (symbol, timestamp, f"+{minutes} minutes"),
            ).fetchone()
        if not row:
            return None, None
        return float(row["last_price"]), row["timestamp"]

    def tradingview_signal_summary(self, target_date: str) -> dict[str, Any]:
        if not self.table_exists("trades"):
            return {}
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT
                    COUNT(*) AS n,
                    SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS approved,
                    SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected
                FROM trades
                WHERE substr(timestamp, 1, 10) = ?
                """,
                (target_date,),
            ).fetchone()

            rejected = {}
            if self.table_exists("rejected_signal_outcomes"):
                rejected_rows = con.execute(
                    """
                    SELECT action,
                           COUNT(*) AS n,
                           AVG(return_15m) AS avg15,
                           AVG(return_60m) AS avg60,
                           AVG(max_favorable_60m) AS mfe60,
                           AVG(max_adverse_60m) AS mae60
                    FROM rejected_signal_outcomes
                    WHERE substr(timestamp, 1, 10) = ?
                      AND label_status IN ('labeled', 'partial')
                    GROUP BY action
                    ORDER BY action
                    """,
                    (target_date,),
                ).fetchall()
                rejected = {row["action"]: dict(row) for row in rejected_rows}

        return {
            "signals": int(rows["n"] or 0),
            "approved": int(rows["approved"] or 0),
            "rejected": int(rows["rejected"] or 0),
            "rejected_outcomes": rejected,
        }

    def intelligence_context_rows(
        self,
        target_date: str,
        symbol: str | None = None,
    ) -> tuple[list[Any], list[Any]]:
        params: list[Any] = [target_date]
        symbol_sql = ""
        if symbol:
            symbol_sql = "AND symbol = ?"
            params.append(symbol.upper())
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT *
                FROM daily_symbol_context
                WHERE market_date = ?
                  {symbol_sql}
                ORDER BY symbol
                """,
                params,
            ).fetchall()
            events = con.execute(
                f"""
                SELECT *
                FROM daily_symbol_events
                WHERE market_date = ?
                  {symbol_sql}
                ORDER BY symbol, event_type
                """,
                params,
            ).fetchall()
        return rows, events

    def latest_by_symbol(
        self,
        table: str,
        time_col: str,
        symbol_filter: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        if not self.table_exists(table):
            return {}

        where = ""
        params: list[Any] = []

        if symbol_filter:
            placeholders = ",".join("?" for _ in symbol_filter)
            where = f"WHERE symbol IN ({placeholders})"
            params.extend(symbol_filter)

        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                WITH ranked AS (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY symbol
                               ORDER BY {time_col} DESC, rowid DESC
                           ) AS rn
                    FROM {table}
                    {where}
                )
                SELECT *
                FROM ranked
                WHERE rn = 1
                """,
                params,
            ).fetchall()
        return {row["symbol"]: dict(row) for row in rows}

    def auto_buy_score_history(self, symbol: str, limit: int = 12) -> list[Any]:
        if not self.table_exists("auto_buy_candidates"):
            return []
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT timestamp, score, decision, hard_block_reason
                FROM auto_buy_candidates
                WHERE symbol = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()

    def recent_buy_rejections(
        self,
        limit: int = 8,
        symbol_filter: list[str] | None = None,
    ) -> list[Any]:
        if not self.table_exists("trades"):
            return []

        where = "WHERE action='buy' AND approved=0"
        params: list[Any] = []

        if symbol_filter:
            placeholders = ",".join("?" for _ in symbol_filter)
            where += f" AND symbol IN ({placeholders})"
            params.extend(symbol_filter)

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT timestamp, symbol, rejection_reason
                FROM trades
                {where}
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()

    def daily_realized_pnl_rows(self, target_date: str) -> list[Any]:
        fill_bearing = fill_bearing_order_condition()
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT timestamp, symbol, action, qty, fill_price
                FROM trades
                WHERE approved = 1
                  AND action IN ('buy', 'sell')
                  AND qty IS NOT NULL
                  AND fill_price IS NOT NULL
                  AND {fill_bearing}
                  AND timestamp LIKE ?
                ORDER BY timestamp ASC, id ASC
                """,
                (f"{target_date}%",),
            ).fetchall()

    def post_session_missing_fills(self, target_date: str) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT id, timestamp, symbol, action, order_id, order_status, qty, fill_price
                FROM trades
                WHERE timestamp LIKE ?
                  AND approved = 1
                  AND order_id IS NOT NULL
                  AND qty IS NOT NULL
                  AND fill_price IS NULL
                ORDER BY id DESC
                """,
                (f"{target_date}%",),
            ).fetchall()

    def db_open_position_rows(self) -> list[Any]:
        fill_bearing = fill_bearing_order_condition()
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT symbol,
                       SUM(CASE
                               WHEN LOWER(action) = 'buy'  THEN COALESCE(qty, 0)
                               WHEN LOWER(action) = 'sell' THEN -COALESCE(qty, 0)
                               ELSE 0
                           END) AS net_qty
                FROM trades
                WHERE order_id IS NOT NULL
                  AND {fill_bearing}
                GROUP BY symbol
                HAVING net_qty > 0
                ORDER BY symbol
                """
            ).fetchall()

    def fill_event_summary_rows(self, target_date: str) -> list[Any]:
        try:
            with get_connection(self.db_path) as con:
                return con.execute(
                    """
                    SELECT event, symbol, side, status, COUNT(*) AS n
                    FROM fill_events
                    WHERE timestamp LIKE ?
                    GROUP BY event, symbol, side, status
                    ORDER BY n DESC
                    LIMIT 20
                    """,
                    (f"{target_date}%",),
                ).fetchall()
        except sqlite3.OperationalError:
            return []

    def signal_count_row(self, target_date: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS approved,
                    SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected,
                    SUM(CASE WHEN order_id IS NOT NULL THEN 1 ELSE 0 END) AS orders
                FROM trades
                WHERE timestamp LIKE ?
                """,
                (f"{target_date}%",),
            ).fetchone()

    def init_historical_signal_events(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS historical_signal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    market_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,

                    first_timestamp TEXT,
                    last_timestamp TEXT,
                    signal_price REAL,
                    signal_source TEXT,

                    raw_signal_count INTEGER NOT NULL DEFAULT 0,
                    has_signal_received INTEGER NOT NULL DEFAULT 0,
                    has_processing_signal INTEGER NOT NULL DEFAULT 0,
                    has_order_placed INTEGER NOT NULL DEFAULT 0,
                    has_rejection_or_gate INTEGER NOT NULL DEFAULT 0,

                    approved INTEGER,
                    order_id TEXT,
                    rejection_reason TEXT,
                    decision_summary TEXT,

                    raw_ids_json TEXT,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,

                    UNIQUE(market_date, symbol, action, first_timestamp, signal_price)
                )
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_historical_signal_events_date_symbol
                ON historical_signal_events(market_date, symbol)
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_historical_signal_events_symbol_time
                ON historical_signal_events(symbol, first_timestamp)
            """)

    def raw_historical_signal_rows(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        symbol: str | None = None,
    ) -> list[Any]:
        where = [
            "market_date IS NOT NULL",
            "symbol IS NOT NULL",
            "action IS NOT NULL",
            "timestamp IS NOT NULL",
            "decision_summary IN ('signal_received', 'processing_signal', 'order_placed', 'rejection_or_gate')",
        ]
        params: list[Any] = []

        if start_date:
            where.append("market_date >= ?")
            params.append(start_date)

        if end_date:
            where.append("market_date <= ?")
            params.append(end_date)

        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT *
                FROM historical_signal_experience
                WHERE {' AND '.join(where)}
                ORDER BY market_date, symbol, action, timestamp, id
                """,
                params,
            ).fetchall()

    def insert_historical_signal_events(
        self,
        events: list[dict[str, Any]],
        *,
        replace: bool = False,
    ) -> int:
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        inserted = 0

        with get_connection(self.db_path) as con:
            if replace:
                con.execute("DELETE FROM historical_signal_events")

            for event in events:
                cur = con.execute(
                    """
                    INSERT OR REPLACE INTO historical_signal_events (
                        market_date, symbol, action,
                        first_timestamp, last_timestamp, signal_price, signal_source,
                        raw_signal_count, has_signal_received, has_processing_signal,
                        has_order_placed, has_rejection_or_gate,
                        approved, order_id, rejection_reason, decision_summary,
                        raw_ids_json, raw_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["market_date"],
                        event["symbol"],
                        event["action"],
                        event["first_timestamp"],
                        event["last_timestamp"],
                        event["signal_price"],
                        event["signal_source"],
                        event["raw_signal_count"],
                        event["has_signal_received"],
                        event["has_processing_signal"],
                        event["has_order_placed"],
                        event["has_rejection_or_gate"],
                        event["approved"],
                        event["order_id"],
                        event["rejection_reason"],
                        event["decision_summary"],
                        json.dumps(event["raw_ids"]),
                        json.dumps(event["raw_rows"], sort_keys=True),
                        now,
                    ),
                )
                inserted += cur.rowcount

        return inserted

    def timing_lesson_summary(self, where_sql: str, params: list[Any]):
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                  COUNT(*) AS signals,
                  SUM(CASE WHEN matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
                  SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS winners,
                  SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) AS losers,
                  ROUND(AVG(entry_delay_minutes), 1) AS avg_entry_delay,
                  ROUND(AVG(exit_delay_minutes), 1) AS avg_exit_delay,
                  ROUND(SUM(realized_pnl), 2) AS total_pnl,
                  ROUND(AVG(realized_pnl), 2) AS avg_pnl,
                  ROUND(AVG(realized_pnl_pct), 2) AS avg_pnl_pct
                FROM historical_signal_outcomes
                WHERE {where_sql}
                """,
                params,
            ).fetchone()

    def timing_lesson_rows(self, group_expr: str, where_sql: str, params: list[Any]) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                  {group_expr} AS bucket,
                  action,
                  COUNT(*) AS n,
                  SUM(CASE WHEN matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
                  SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS winners,
                  SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) AS losers,
                  ROUND(AVG(entry_delay_minutes), 1) AS avg_entry_delay,
                  ROUND(AVG(exit_delay_minutes), 1) AS avg_exit_delay,
                  ROUND(AVG(holding_minutes), 1) AS avg_holding_minutes,
                  ROUND(AVG(realized_pnl), 2) AS avg_pnl,
                  ROUND(SUM(realized_pnl), 2) AS total_pnl,
                  ROUND(AVG(realized_pnl_pct), 2) AS avg_pnl_pct
                FROM historical_signal_outcomes
                WHERE {where_sql}
                GROUP BY {group_expr}, action
                ORDER BY total_pnl DESC, matched DESC, n DESC
                """,
                params,
            ).fetchall()

    def timing_lesson_detail_rows(self, where_sql: str, params: list[Any]) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT *
                FROM historical_signal_outcomes
                WHERE {where_sql}
                ORDER BY market_date, symbol, signal_timestamp
                LIMIT 150
                """,
                params,
            ).fetchall()

    def strategy_learner_rows(self, cutoff: str) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT
                    symbol,
                    realized_pnl,
                    trend_direction,
                    trend_strength,
                    market_bias,
                    risk_level,
                    entry_quality,
                    macro_regime,
                    market_bias_effective,
                    fundamental_score,
                    session_trend_label,
                    session_trend_score,
                    session_momentum_5m_pct,
                    session_momentum_15m_pct,
                    session_momentum_30m_pct,
                    prediction_score,
                    prediction_decision,
                    setup_label,
                    setup_policy_action,
                    buy_opportunity_score,
                    buy_opportunity_recommendation,
                    exit_timestamp
                FROM matched_trades
                WHERE exit_timestamp >= ?
                ORDER BY exit_timestamp ASC
                """,
                (cutoff,),
            ).fetchall()

    def bar_pattern_strategy_rows(self, cutoff: str) -> list[Any]:
        if not self.table_exists("bar_pattern_features"):
            return []
        columns = self.table_columns("bar_pattern_features")

        def expr(name: str, alias: str | None = None) -> str:
            alias = alias or name
            return name if name in columns else f"NULL AS {alias}"

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                    symbol,
                    bar_timestamp,
                    {expr("timeframe")},
                    {expr("pattern_label")},
                    {expr("pattern_score")},
                    {expr("opportunity_action")},
                    {expr("opportunity_quality")},
                    {expr("long_opportunity_score")},
                    {expr("sell_opportunity_score")},
                    {expr("forward_return_pct")},
                    {expr("forward_mfe_pct")},
                    {expr("forward_mae_pct")},
                    {expr("horizon_bars")},
                    {expr("feature_version")},
                    {expr("runtime_effect")}
                FROM bar_pattern_features
                WHERE substr(bar_timestamp, 1, 10) >= ?
                ORDER BY bar_timestamp ASC, symbol ASC
                """,
                (cutoff,),
            ).fetchall()
