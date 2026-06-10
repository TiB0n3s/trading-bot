"""Repository boundary for experience-model prediction data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class ExperienceModelRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def init_prediction_tables(self, timing_columns: dict[str, str]) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_symbol_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    market_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,

                    prediction_score REAL,
                    probability_of_profit REAL,
                    probability_of_approval REAL,
                    probability_of_order REAL,
                    expected_pnl REAL,
                    expected_win_rate REAL,

                    confidence TEXT,
                    sample_size INTEGER,
                    similarity_basis TEXT,
                    reason TEXT,

                    timing_score REAL,
                    recommended_entry_timing TEXT,
                    recommended_exit_timing TEXT,
                    historical_avg_entry_delay REAL,
                    historical_avg_exit_delay REAL,
                    historical_timing_sample_size INTEGER,
                    timing_reason TEXT,

                    trend_score REAL,
                    trend_label TEXT,
                    trend_regime TEXT,
                    trend_confidence TEXT,
                    trend_similarity_sample_size INTEGER,
                    trend_reason TEXT,

                    raw_json TEXT,
                    prediction_generated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,

                    UNIQUE(market_date, symbol)
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_symbol_predictions_date_symbol
                ON daily_symbol_predictions(market_date, symbol)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_symbol_predictions_symbol_date
                ON daily_symbol_predictions(symbol, market_date)
                """
            )

            existing_cols = {
                row["name"]
                for row in con.execute("PRAGMA table_info(daily_symbol_predictions)").fetchall()
            }
            for col, col_type in timing_columns.items():
                if col not in existing_cols:
                    con.execute(f"ALTER TABLE daily_symbol_predictions ADD COLUMN {col} {col_type}")
            if "prediction_generated_at" not in existing_cols:
                con.execute(
                    "ALTER TABLE daily_symbol_predictions ADD COLUMN prediction_generated_at TEXT"
                )

    def load_target_context(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM daily_symbol_context
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (market_date, symbol),
            ).fetchone()

    def load_target_events(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM daily_symbol_events
                WHERE market_date = ?
                  AND symbol = ?
                ORDER BY id
                """,
                (market_date, symbol),
            ).fetchall()

    def load_historical_contexts(self, market_date: str, symbol: str | None = None):
        params: list[Any] = [market_date]
        symbol_filter = ""
        if symbol:
            symbol_filter = "AND symbol = ?"
            params.append(symbol)

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT *
                FROM daily_symbol_context
                WHERE market_date < ?
                  {symbol_filter}
                ORDER BY market_date DESC, symbol
                """,
                params,
            ).fetchall()

    def events_for_context(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT event_type, expected_market_impact, trade_relevance,
                       consumer_appetite_score, profit_potential_score,
                       supply_chain_risk_score, competitive_risk_score
                FROM daily_symbol_events
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (market_date, symbol),
            ).fetchall()

    def trade_rows_for_context(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM trades
                WHERE timestamp LIKE ?
                  AND symbol = ?
                """,
                (f"{market_date}%", symbol),
            ).fetchall()

    def historical_signal_event_rows(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM historical_signal_events
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (market_date, symbol),
            ).fetchall()

    def historical_signal_experience_rows(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM historical_signal_experience
                WHERE market_date = ?
                  AND symbol = ?
                  AND decision_summary IN ('signal_received', 'processing_signal', 'order_placed')
                """,
                (market_date, symbol),
            ).fetchall()

    def matched_trade_rows_for_context(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT realized_pnl, realized_pnl_pct
                FROM matched_trades
                WHERE exit_timestamp LIKE ?
                  AND symbol = ?
                """,
                (f"{market_date}%", symbol),
            ).fetchall()

    def historical_trade_outcome_rows(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT realized_pnl, realized_pnl_pct
                FROM historical_trade_outcomes
                WHERE exit_timestamp LIKE ?
                  AND symbol = ?
                """,
                (f"{market_date}%", symbol),
            ).fetchall()

    def trend_context_for_symbol(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM historical_trend_context
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (market_date, symbol),
            ).fetchone()

    def trend_similarity_rows(self, market_date: str, symbol: str, target: Any):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT
                    t.market_date,
                    t.symbol,
                    t.trend_label,
                    t.trend_regime,
                    t.relative_strength_score,
                    t.distance_from_sma_20_pct,
                    COUNT(s.id) AS signal_rows,
                    SUM(CASE WHEN s.matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched_signals,
                    SUM(CASE WHEN s.realized_pnl > 0 THEN 1 ELSE 0 END) AS winners,
                    SUM(CASE WHEN s.realized_pnl < 0 THEN 1 ELSE 0 END) AS losers,
                    AVG(s.realized_pnl) AS avg_pnl,
                    SUM(s.realized_pnl) AS total_pnl,
                    AVG(s.realized_pnl_pct) AS avg_pnl_pct
                FROM historical_trend_context t
                LEFT JOIN historical_signal_outcomes s
                  ON s.market_date = t.market_date
                 AND s.symbol = t.symbol
                WHERE t.market_date < ?
                  AND (
                        t.trend_label = ?
                     OR t.trend_regime = ?
                     OR t.symbol = ?
                  )
                GROUP BY t.market_date, t.symbol
                HAVING matched_signals > 0
                ORDER BY
                  CASE WHEN t.symbol = ? THEN 0 ELSE 1 END,
                  CASE WHEN t.trend_label = ? THEN 0 ELSE 1 END,
                  t.market_date DESC
                LIMIT 40
                """,
                (
                    market_date,
                    target["trend_label"],
                    target["trend_regime"],
                    symbol,
                    symbol,
                    target["trend_label"],
                ),
            ).fetchall()

    def timing_lesson_row(self, market_date: str, symbol: str, symbol_filter: bool):
        params: list[Any] = [market_date]
        where = ["action = 'buy'", "market_date <= ?"]
        if symbol_filter:
            where.append("symbol = ?")
            params.append(symbol)
        where_sql = " AND ".join(where)

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                  entry_timing_label AS bucket,
                  action,
                  COUNT(*) AS n,
                  SUM(CASE WHEN matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
                  ROUND(AVG(entry_delay_minutes), 2) AS avg_entry_delay,
                  ROUND(AVG(exit_delay_minutes), 2) AS avg_exit_delay,
                  ROUND(AVG(realized_pnl), 4) AS avg_pnl,
                  ROUND(SUM(realized_pnl), 4) AS total_pnl,
                  ROUND(AVG(realized_pnl_pct), 4) AS avg_pnl_pct
                FROM historical_signal_outcomes
                WHERE {where_sql}
                GROUP BY entry_timing_label, action
                HAVING matched > 0
                ORDER BY total_pnl DESC, matched DESC
                LIMIT 1
                """,
                params,
            ).fetchone()

    def weekly_symbol_performance_row(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT
                    COUNT(*) AS trades,
                    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) AS losses,
                    SUM(COALESCE(realized_pnl, 0)) AS pnl,
                    AVG(realized_pnl) AS expectancy,
                    AVG(realized_pnl_pct) AS avg_pnl_pct
                FROM matched_trades
                WHERE symbol = ?
                  AND entry_timestamp >= date(?, 'weekday 1', '-7 days')
                  AND entry_timestamp < date(?, '+1 day')
                """,
                (symbol, market_date, market_date),
            ).fetchone()

    def upsert_prediction(self, row: dict[str, Any], columns: list[str]) -> None:
        values = [row.get(c) for c in columns]
        placeholders = ", ".join(["?"] * len(columns))
        update_cols = [c for c in columns if c not in ("market_date", "symbol", "created_at")]
        update_sql = ", ".join(f"{c}=excluded.{c}" for c in update_cols)

        with get_connection(self.db_path) as con:
            con.execute(
                f"""
                INSERT INTO daily_symbol_predictions ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(market_date, symbol)
                DO UPDATE SET {update_sql}
                """,
                values,
            )

    def prediction_symbols(self, market_date: str) -> list[str]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT symbol
                FROM daily_symbol_context
                WHERE market_date = ?
                ORDER BY symbol
                """,
                (market_date,),
            ).fetchall()
        return [row["symbol"] for row in rows]
