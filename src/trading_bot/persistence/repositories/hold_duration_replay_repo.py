"""Read-only data access for hold-duration replay reports."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from db import DB_PATH, get_read_connection


class HoldDurationReplayRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    @staticmethod
    def _table_exists(con, table: str) -> bool:
        return (
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _next_date(value: str) -> str:
        return (date.fromisoformat(value[:10]) + timedelta(days=1)).isoformat()

    def auto_buy_candidates_between(
        self,
        start_date: str,
        end_date: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not Path(self.db_path).exists():
            return []
        with get_read_connection(self.db_path) as con:
            if not self._table_exists(con, "auto_buy_candidates"):
                return []
            limit_sql = f"LIMIT {int(limit)}" if limit and limit > 0 else ""
            rows = con.execute(
                f"""
                SELECT
                    id,
                    timestamp,
                    symbol,
                    signal_source,
                    decision,
                    score,
                    reason,
                    setup_label,
                    setup_recommendation,
                    setup_score,
                    hard_block_reason,
                    live_buy_enabled,
                    order_submitted
                FROM auto_buy_candidates
                WHERE timestamp >= ?
                  AND timestamp < ?
                ORDER BY julianday(timestamp) ASC, id ASC
                {limit_sql}
                """,
                (start_date, self._next_date(end_date)),
            ).fetchall()
        return [dict(row) for row in rows]

    def replay_price_points(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        if not symbols or not Path(self.db_path).exists():
            return []
        with get_read_connection(self.db_path) as con:
            placeholders = ", ".join("?" for _ in symbols)
            if self._table_exists(con, "bar_pattern_features"):
                rows = con.execute(
                    f"""
                    SELECT
                        bar_timestamp AS timestamp,
                        symbol,
                        close AS last_price,
                        pattern_label,
                        pattern_score,
                        opportunity_action,
                        opportunity_quality,
                        long_opportunity_score,
                        sell_opportunity_score,
                        'bar_pattern_features.close_1m' AS price_source
                    FROM bar_pattern_features INDEXED BY idx_bar_pattern_features_symbol_ts
                    WHERE symbol IN ({placeholders})
                      AND bar_timestamp >= ?
                      AND bar_timestamp < ?
                      AND timeframe = '1m'
                      AND close IS NOT NULL
                    ORDER BY symbol, bar_timestamp
                    """,
                    [*symbols, start_date, self._next_date(end_date)],
                ).fetchall()
                return [dict(row) for row in rows]

            if not self._table_exists(con, "feature_snapshots"):
                return []
            rows = con.execute(
                f"""
                SELECT
                    timestamp,
                    symbol,
                    last_price,
                    NULL AS pattern_label,
                    NULL AS pattern_score,
                    NULL AS opportunity_action,
                    NULL AS opportunity_quality,
                    NULL AS long_opportunity_score,
                    NULL AS sell_opportunity_score,
                    'feature_snapshots.last_price' AS price_source
                FROM feature_snapshots
                WHERE symbol IN ({placeholders})
                  AND timestamp >= ?
                  AND timestamp < ?
                  AND last_price IS NOT NULL
                ORDER BY symbol, timestamp, id
                """,
                [*symbols, start_date, self._next_date(end_date)],
            ).fetchall()
        return [dict(row) for row in rows]

    def feature_price_points(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        return self.replay_price_points(symbols, start_date, end_date)
