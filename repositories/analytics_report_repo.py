"""Repository boundary for analytics_report.py reads."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection
from repositories.trade_accounting import fill_bearing_order_condition


class AnalyticsReportRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def db_exists(self) -> bool:
        return self.db_path.exists()

    def execution_summary(self, clause: str, params: tuple[Any, ...]) -> dict[str, Any]:
        fill_bearing = fill_bearing_order_condition()
        with get_connection(self.db_path) as con:
            row = con.execute(
                f"""
                SELECT
                  SUM(CASE WHEN action='buy'  AND (rejection_reason IS NULL
                               OR rejection_reason NOT LIKE 'synthetic_bracket_exit:%')
                           THEN 1 ELSE 0 END) AS filled_buys,
                  SUM(CASE WHEN action='sell' AND (rejection_reason IS NULL
                               OR rejection_reason NOT LIKE 'synthetic_bracket_exit:%')
                           THEN 1 ELSE 0 END) AS filled_sells,
                  SUM(CASE WHEN rejection_reason LIKE 'synthetic_bracket_exit:%'
                           THEN 1 ELSE 0 END) AS synth_exits
                FROM trades
                WHERE approved = 1
                  AND {fill_bearing}
                  AND qty IS NOT NULL
                  AND fill_price IS NOT NULL
                  {clause}
                """,
                params,
            ).fetchone()
        return dict(row)

    def open_position_rows(self) -> list[Any]:
        fill_bearing = fill_bearing_order_condition()
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT symbol,
                    SUM(CASE WHEN action='buy' THEN COALESCE(qty,0)
                             ELSE -COALESCE(qty,0) END) AS net_qty
                FROM trades
                WHERE order_id IS NOT NULL
                  AND {fill_bearing}
                GROUP BY symbol
                HAVING net_qty > 0
                """
            ).fetchall()

    def fill_event_count(self, clause: str, params: tuple[Any, ...]) -> int | None:
        try:
            with get_connection(self.db_path) as con:
                row = con.execute(
                    f"SELECT COUNT(*) AS n FROM fill_events WHERE 1=1{clause}",
                    params,
                ).fetchone()
            return int(row["n"] or 0)
        except sqlite3.OperationalError:
            return None

    def rejection_category_rows(self, clause: str, params: tuple[Any, ...]) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                  CASE
                    WHEN instr(rejection_reason, ':') > 0
                      THEN substr(rejection_reason, 1, instr(rejection_reason, ':') - 1)
                    ELSE 'uncategorized'
                  END AS category,
                  COUNT(*) AS n
                FROM trades
                WHERE approved = 0
                  AND rejection_reason IS NOT NULL
                  {clause}
                GROUP BY category
                ORDER BY n DESC
                """,
                params,
            ).fetchall()

    def fifo_trade_rows(self, clause: str, params: tuple[Any, ...]) -> list[Any]:
        fill_bearing = fill_bearing_order_condition()
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT timestamp, symbol, action, qty, fill_price, signal_price
                FROM trades
                WHERE approved = 1
                  AND action IN ('buy', 'sell')
                  AND qty IS NOT NULL
                  AND fill_price IS NOT NULL
                  AND {fill_bearing}
                  {clause}
                ORDER BY timestamp ASC, id ASC
                """,
                params,
            ).fetchall()

    def session_momentum_attribution_rows(
        self,
        clause: str,
        params: tuple[Any, ...],
    ) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                    COALESCE(session_trend_label, 'unknown') AS label,
                    COUNT(*) AS total,
                    SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS approved,
                    SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected
                FROM trades
                WHERE LOWER(action) = 'buy'
                  {clause}
                GROUP BY COALESCE(session_trend_label, 'unknown')
                ORDER BY total DESC
                """,
                params,
            ).fetchall()

    def matched_summary(
        self,
        matched_clause: str,
        params: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        try:
            with get_connection(self.db_path) as con:
                row = con.execute(
                    f"""
                    SELECT
                      COUNT(*) AS trades,
                      COALESCE(SUM(realized_pnl), 0) AS pnl,
                      COALESCE(AVG(realized_pnl), 0) AS expectancy,
                      CASE WHEN COUNT(*) > 0 THEN
                        SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*)
                      ELSE 0 END AS win_rate
                    FROM matched_trades
                    WHERE 1=1 {matched_clause}
                    """,
                    params,
                ).fetchone()
            return dict(row)
        except sqlite3.OperationalError:
            return None

    def matched_profit_factor_row(
        self,
        matched_clause: str,
        params: tuple[Any, ...],
    ) -> dict[str, Any]:
        with get_connection(self.db_path) as con:
            row = con.execute(
                f"""
                SELECT
                  COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END), 0) AS gross_profit,
                  COALESCE(ABS(SUM(CASE WHEN realized_pnl < 0 THEN realized_pnl ELSE 0 END)), 0) AS gross_loss
                FROM matched_trades
                WHERE 1=1 {matched_clause}
                """,
                params,
            ).fetchone()
        return dict(row)

    def matched_symbol_rows(self, matched_clause: str, params: tuple[Any, ...]) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT symbol, COUNT(*) AS trades,
                       SUM(realized_pnl) AS pnl, AVG(realized_pnl) AS expectancy,
                       SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS win_rate
                FROM matched_trades
                WHERE 1=1 {matched_clause}
                GROUP BY symbol
                ORDER BY pnl DESC
                """,
                params,
            ).fetchall()

    def matched_macro_rows(self, matched_clause: str, params: tuple[Any, ...]) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT macro_regime, COUNT(*) AS n,
                       SUM(realized_pnl) AS pnl, AVG(realized_pnl) AS expectancy
                FROM matched_trades
                WHERE macro_regime IS NOT NULL {matched_clause}
                GROUP BY macro_regime
                ORDER BY pnl DESC
                """,
                params,
            ).fetchall()

    def matched_trend_rows(self, matched_clause: str, params: tuple[Any, ...]) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT trend_direction, trend_strength, COUNT(*) AS n,
                       SUM(realized_pnl) AS pnl, AVG(realized_pnl) AS expectancy
                FROM matched_trades
                WHERE trend_direction IS NOT NULL {matched_clause}
                GROUP BY trend_direction, trend_strength
                ORDER BY pnl DESC
                """,
                params,
            ).fetchall()

    def data_quality_summary(
        self,
        matched_clause: str,
        params: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        try:
            with get_connection(self.db_path) as con:
                row = con.execute(
                    f"""
                    SELECT COUNT(*) AS n, COALESCE(SUM(realized_pnl), 0) AS pnl
                    FROM matched_trades
                    WHERE 1=1 {matched_clause}
                    """,
                    params,
                ).fetchone()
            return dict(row)
        except sqlite3.OperationalError:
            return None

    def missing_fill_rows(self, clause: str, params: tuple[Any, ...]) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT id, timestamp, symbol, action, qty, signal_price, fill_price,
                       order_id, order_status
                FROM trades
                WHERE approved = 1
                  AND action IN ('buy', 'sell')
                  AND qty IS NOT NULL
                  AND fill_price IS NULL
                  {clause}
                ORDER BY timestamp
                """,
                params,
            ).fetchall()
