from __future__ import annotations

import sqlite3
from typing import Any


class OpsCheckIntelligenceQueriesMixin:
    def recent_market_date_rows(self, table_name: str) -> list[sqlite3.Row]:
        return self._fetchall(
            f"""
            SELECT market_date, COUNT(*) AS n
            FROM {table_name}
            GROUP BY market_date
            ORDER BY market_date DESC
            LIMIT 7
            """
        )

    def prediction_confidence_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT COALESCE(confidence, 'missing') AS confidence, COUNT(*) AS n
            FROM daily_symbol_predictions
            WHERE market_date = ?
            GROUP BY COALESCE(confidence, 'missing')
            ORDER BY confidence
            """,
            (target_date,),
        )

    def intelligence_freshness_row(self, target_date: str) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT
              (SELECT MAX(created_at)
               FROM daily_symbol_events
               WHERE market_date = ?) AS latest_event_at,
              (SELECT MAX(updated_at)
               FROM daily_symbol_context
               WHERE market_date = ?) AS latest_context_at,
              (SELECT MAX(updated_at)
               FROM daily_symbol_predictions
               WHERE market_date = ?) AS latest_prediction_at
            """,
            (target_date, target_date, target_date),
        )

    def event_source_rows(self, target_date: str) -> list[sqlite3.Row]:
        if not self.table_exists("daily_symbol_events"):
            return []
        columns = self.table_columns("daily_symbol_events")
        raw_expr = "raw_json" if "raw_json" in columns else "NULL AS raw_json"
        summary_expr = "event_summary" if "event_summary" in columns else "NULL AS event_summary"
        impact_expr = (
            "expected_market_impact"
            if "expected_market_impact" in columns
            else "NULL AS expected_market_impact"
        )
        relevance_expr = (
            "trade_relevance" if "trade_relevance" in columns else "NULL AS trade_relevance"
        )
        return self._fetchall(
            f"""
            SELECT
                symbol,
                event_type,
                {summary_expr},
                {impact_expr},
                {relevance_expr},
                confidence,
                source,
                source_url,
                {raw_expr},
                created_at
            FROM daily_symbol_events
            WHERE market_date = ?
            ORDER BY created_at ASC, id ASC
            """,
            (target_date,),
        )

    def context_freshness_row(self, target_date: str) -> dict[str, Any]:
        def latest(table: str, column: str, where_column: str | None = None):
            if not self.table_exists(table):
                return None
            if column not in self.table_columns(table):
                return None
            where_sql = ""
            params: tuple[Any, ...] = ()
            if where_column and where_column in self.table_columns(table):
                where_sql = f"WHERE {where_column} = ?"
                params = (target_date,)
            row = self._fetchone(
                f"SELECT MAX({column}) AS latest_at FROM {table} {where_sql}",
                params,
            )
            return row["latest_at"] if row else None

        def count(table: str, where_column: str | None = None):
            if not self.table_exists(table):
                return None
            where_sql = ""
            params: tuple[Any, ...] = ()
            if where_column and where_column in self.table_columns(table):
                where_sql = f"{where_column} = ?"
                params = (target_date,)
            return self.table_count(table, where_sql, params)

        return {
            "daily_symbol_context_latest_at": latest(
                "daily_symbol_context", "updated_at", "market_date"
            ),
            "daily_symbol_context_rows": count("daily_symbol_context", "market_date"),
            "daily_symbol_events_latest_at": latest(
                "daily_symbol_events", "created_at", "market_date"
            ),
            "daily_symbol_events_rows": count("daily_symbol_events", "market_date"),
            "daily_symbol_predictions_latest_at": latest(
                "daily_symbol_predictions", "updated_at", "market_date"
            ),
            "daily_symbol_predictions_rows": count("daily_symbol_predictions", "market_date"),
            "feature_snapshots_latest_at": latest("feature_snapshots", "timestamp"),
            "feature_snapshots_rows": count("feature_snapshots"),
            "session_momentum_latest_at": latest("session_momentum", "updated_at"),
            "session_momentum_rows": count("session_momentum"),
        }

    def intelligence_row_count(self, table_name: str, target_date: str) -> int:
        row = self._fetchone(
            f"""
            SELECT COUNT(*) AS n
            FROM {table_name}
            WHERE market_date = ?
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def context_bias_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT COALESCE(bias, 'missing') AS bias, COUNT(*) AS n
            FROM daily_symbol_context
            WHERE market_date = ?
            GROUP BY COALESCE(bias, 'missing')
            ORDER BY bias
            """,
            (target_date,),
        )

    def context_avoid_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT symbol, bias, risk_level, entry_quality, avoid_type, reason
            FROM daily_symbol_context
            WHERE market_date = ?
              AND bias = 'avoid'
            ORDER BY symbol
            """,
            (target_date,),
        )

    def latest_context_update_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT symbol, updated_at
            FROM daily_symbol_context
            WHERE market_date = ?
            ORDER BY updated_at DESC, symbol
            LIMIT 10
            """,
            (target_date,),
        )

    def trend_context_summary_row(
        self,
        where_sql: str,
        params: list[Any],
    ) -> sqlite3.Row | None:
        return self._fetchone(
            f"""
            SELECT
              COUNT(*) AS context_rows,
              COUNT(DISTINCT market_date) AS dates,
              COUNT(DISTINCT symbol) AS symbols
            FROM historical_trend_context t
            WHERE {where_sql}
            """,
            tuple(params),
        )

    def trend_context_bucket_rows(
        self,
        group_expr: str,
        where_sql: str,
        params: list[Any],
    ) -> list[sqlite3.Row]:
        return self._fetchall(
            f"""
            SELECT
              {group_expr} AS bucket,
              COUNT(DISTINCT t.symbol || ':' || t.market_date) AS context_rows,
              COUNT(s.id) AS signal_rows,
              SUM(CASE WHEN s.matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched_signals,
              SUM(CASE WHEN s.realized_pnl > 0 THEN 1 ELSE 0 END) AS winners,
              SUM(CASE WHEN s.realized_pnl < 0 THEN 1 ELSE 0 END) AS losers,
              ROUND(AVG(s.realized_pnl), 2) AS avg_signal_pnl,
              ROUND(SUM(s.realized_pnl), 2) AS total_signal_pnl,
              ROUND(AVG(s.realized_pnl_pct), 2) AS avg_signal_pnl_pct,
              ROUND(AVG(t.trend_1d_pct), 2) AS avg_1d,
              ROUND(AVG(t.trend_5d_pct), 2) AS avg_5d,
              ROUND(AVG(t.trend_10d_pct), 2) AS avg_10d,
              ROUND(AVG(t.relative_strength_score), 1) AS avg_rs,
              ROUND(AVG(t.distance_from_sma_20_pct), 2) AS avg_dist20
            FROM historical_trend_context t
            LEFT JOIN historical_signal_outcomes s
              ON s.market_date = t.market_date
             AND s.symbol = t.symbol
            WHERE {where_sql}
            GROUP BY {group_expr}
            ORDER BY total_signal_pnl DESC, matched_signals DESC, signal_rows DESC
            """,
            tuple(params),
        )

    def session_gate_snapshot_rows(
        self,
        date_clause: str,
        params: list[Any],
    ) -> list[sqlite3.Row]:
        return self._fetchall(
            f"""
            SELECT
                ds.id,
                ds.trade_id,
                ds.symbol,
                ds.decision_time,
                ds.final_decision,
                ds.approved,
                ds.rejection_reason,
                ds.session_trend_label,
                ds.session_trend_score,
                ds.setup_policy_action,
                ds.prediction_score,
                ds.trend_direction,
                ds.trend_strength,
                mt.realized_pnl,
                mt.realized_pnl_pct
            FROM decision_snapshots ds
            LEFT JOIN matched_trades mt ON mt.id = ds.trade_id
            WHERE ds.action = 'buy'
            {date_clause}
            ORDER BY ds.decision_time
            """,
            tuple(params),
        )

    def session_gate_blocked_trade_rows(
        self,
        date_clause: str,
        params: list[Any],
    ) -> list[sqlite3.Row]:
        trade_clause = date_clause.replace("ds.", "t.").replace("decision_time", "timestamp")
        return self._fetchall(
            f"""
            SELECT t.symbol, t.timestamp, t.rejection_reason
            FROM trades t
            WHERE t.rejection_reason LIKE '%session%'
              AND t.action = 'buy'
            {trade_clause}
            ORDER BY t.timestamp
            """,
            tuple(params),
        )
