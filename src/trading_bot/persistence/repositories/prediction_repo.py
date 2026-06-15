"""Repository boundary for daily symbol predictions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH, init_prediction_tables


def _prediction_generated_at_expr(columns: set[str]) -> str:
    if "prediction_generated_at" in columns:
        return "prediction_generated_at"
    return "NULL"


def _column_expr(columns: set[str], column_name: str) -> str:
    if column_name in columns:
        return column_name
    return f"NULL AS {column_name}"


class PredictionRepository:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or DB_PATH)

    def init_tables(self) -> None:
        init_prediction_tables()

    def daily_predictions(self, market_date: str) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []

        with sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=0.05,
        ) as con:
            con.row_factory = sqlite3.Row
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_symbol_predictions'"
            ).fetchone()
            if not exists:
                return []
            columns = {
                row["name"]
                for row in con.execute("PRAGMA table_info(daily_symbol_predictions)").fetchall()
            }
            prediction_generated_at_expr = _prediction_generated_at_expr(columns)
            updated_at_expr = _column_expr(columns, "updated_at")
            rows = con.execute(
                f"""
                SELECT market_date, symbol, prediction_score, probability_of_profit,
                       probability_of_order, expected_pnl, confidence, sample_size,
                       reason, timing_score, recommended_entry_timing,
                       recommended_exit_timing, trend_score, trend_label,
                       trend_regime, trend_confidence, {updated_at_expr},
                       {prediction_generated_at_expr} AS prediction_generated_at
                FROM daily_symbol_predictions
                WHERE market_date = ?
                """,
                (market_date,),
            ).fetchall()

        return [dict(row) for row in rows]

    def table_exists(self, table_name: str) -> bool:
        if not self.db_path.exists():
            return False

        with sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=0.05,
        ) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        return row is not None

    def serving_prediction_row(self, market_date: str, symbol: str) -> dict[str, Any] | None:
        if not self.db_path.exists():
            return None

        with sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=0.05,
        ) as con:
            con.row_factory = sqlite3.Row
            columns = {
                row["name"]
                for row in con.execute("PRAGMA table_info(daily_symbol_predictions)").fetchall()
            }
            prediction_generated_at_expr = _prediction_generated_at_expr(columns)
            probability_of_profit_expr = _column_expr(columns, "probability_of_profit")
            probability_of_approval_expr = _column_expr(columns, "probability_of_approval")
            probability_of_order_expr = _column_expr(columns, "probability_of_order")
            row = con.execute(
                f"""
                SELECT market_date, symbol, prediction_score, confidence,
                       sample_size, trend_label, timing_score, reason,
                       {probability_of_profit_expr},
                       {probability_of_approval_expr},
                       {probability_of_order_expr},
                       {prediction_generated_at_expr} AS prediction_generated_at
                FROM daily_symbol_predictions
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (market_date, symbol.upper()),
            ).fetchone()

        return dict(row) if row else None

    def intelligence_prediction_report_rows(
        self,
        market_date: str,
        symbol: str | None = None,
    ) -> list[sqlite3.Row]:
        params: list[Any] = [market_date]
        symbol_sql = ""
        if symbol:
            symbol_sql = "AND p.symbol = ?"
            params.append(symbol.upper())

        strong_join = ""
        strong_columns = """
                NULL AS strong_session_return_pct,
                NULL AS strong_primary_status,
                NULL AS strong_primary_blocker,
                NULL AS strong_auto_buy_candidates,
                NULL AS strong_auto_buy_max_score
        """
        if self.table_exists("strong_day_participation"):
            strong_columns = """
                s.session_return_pct AS strong_session_return_pct,
                s.primary_status AS strong_primary_status,
                s.primary_blocker AS strong_primary_blocker,
                s.auto_buy_candidate_count AS strong_auto_buy_candidates,
                s.auto_buy_max_score AS strong_auto_buy_max_score
            """
            strong_join = """
            LEFT JOIN strong_day_participation s
              ON s.market_date = p.market_date
             AND s.symbol = p.symbol
             AND s.min_session_pct = (
                 SELECT MIN(min_session_pct)
                 FROM strong_day_participation
                 WHERE market_date = p.market_date
             )
            """

        with sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=0.05,
        ) as con:
            con.row_factory = sqlite3.Row
            return con.execute(
                f"""
                SELECT
                    p.*,
                    c.bias,
                    c.risk_level,
                    c.entry_quality,
                    c.catalyst_score,
                    c.supply_chain_risk_score,
                    c.competitive_risk_score,
                    {strong_columns}
                FROM daily_symbol_predictions p
                LEFT JOIN daily_symbol_context c
                  ON c.market_date = p.market_date
                 AND c.symbol = p.symbol
                {strong_join}
                WHERE p.market_date = ?
                  {symbol_sql}
                ORDER BY p.prediction_score DESC, p.symbol
                """,
                tuple(params),
            ).fetchall()

    def prediction_report_labeled_rows(
        self,
        *,
        symbol: str | None = None,
        horizon: str = "15m",
        session: str | None = None,
        target_date: str | None = None,
        last_n_days: int | None = None,
        start_date: str | None = None,
    ) -> list[sqlite3.Row]:
        clauses = []
        params: list[Any] = []

        horizon_col = {
            "5m": "ls.ret_fwd_5m",
            "15m": "ls.ret_fwd_15m",
            "30m": "ls.ret_fwd_30m",
        }[horizon]
        clauses.append(f"{horizon_col} IS NOT NULL")

        if symbol:
            clauses.append("fs.symbol = ?")
            params.append(symbol.upper())

        if session:
            clauses.append("fs.market_session = ?")
            params.append(session)

        if target_date:
            clauses.append("fs.timestamp LIKE ?")
            params.append(f"{target_date}%")
        elif last_n_days is not None:
            clauses.append("substr(fs.timestamp, 1, 10) >= ?")
            params.append(start_date)

        where_sql = " AND ".join(clauses)

        with sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=0.05,
        ) as con:
            con.row_factory = sqlite3.Row
            return con.execute(
                f"""
                SELECT
                    fs.id AS snapshot_id,
                    fs.timestamp,
                    fs.symbol,
                    fs.market_session,
                    fs.market_bias,
                    fs.trend_direction,
                    fs.trend_strength,
                    fs.relative_strength_5m,
                    fs.distance_from_vwap,
                    fs.ret_5m,
                    fs.ret_15m,
                    fs.bar_timeframe,
                    fs.bar_count,
                    fs.setup_label,
                    fs.setup_recommendation,
                    fs.setup_score,
                    fs.setup_confidence,
                    fs.setup_key,
                    ls.ret_fwd_5m,
                    ls.ret_fwd_15m,
                    ls.ret_fwd_30m,
                    ls.max_up_15m,
                    ls.max_down_15m,
                    ls.outcome_label
                FROM feature_snapshots fs
                JOIN labeled_setups ls
                  ON ls.snapshot_id = fs.id
                WHERE {where_sql}
                ORDER BY fs.timestamp ASC
                """,
                params,
            ).fetchall()

    def prediction_report_trade_rows(
        self,
        *,
        symbol: str | None = None,
        target_date: str | None = None,
        last_n_days: int | None = None,
        start_date: str | None = None,
    ) -> list[sqlite3.Row]:
        clauses = []
        params: list[Any] = []

        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())

        if target_date:
            clauses.append("timestamp LIKE ?")
            params.append(f"{target_date}%")
        elif last_n_days is not None:
            clauses.append("substr(timestamp, 1, 10) >= ?")
            params.append(start_date)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=0.05,
        ) as con:
            con.row_factory = sqlite3.Row
            return con.execute(
                f"""
                SELECT
                    id,
                    timestamp,
                    symbol,
                    action,
                    approved,
                    rejection_reason,
                    confidence,
                    market_bias,
                    trend_direction,
                    trend_strength,
                    setup_label,
                    setup_policy_action,
                    setup_policy_reason
                FROM trades
                {where_sql}
                ORDER BY timestamp ASC
                """,
                params,
            ).fetchall()
