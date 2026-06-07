"""Repository reads for historical bar-pattern feature coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH


class HistoricalBarCoverageRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def exists(self) -> bool:
        return self.db_path.exists()

    def _connect(self):
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _table_exists(con: sqlite3.Connection, table: str) -> bool:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
        return {
            row["name"]
            for row in con.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def coverage_payload(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.exists():
            return None
        with self._connect() as con:
            if not self._table_exists(con, "bar_pattern_features"):
                return {"table_exists": False}
            columns = self._table_columns(con, "bar_pattern_features")

            def has_all(*names: str) -> bool:
                return all(name in columns for name in names)

            raw_contract_expr = (
                """
                    SUM(CASE
                        WHEN open IS NOT NULL
                         AND high IS NOT NULL
                         AND low IS NOT NULL
                         AND close IS NOT NULL
                         AND volume IS NOT NULL
                         AND vwap IS NOT NULL
                         AND bar_interval_start_ts IS NOT NULL
                        THEN 1 ELSE 0 END) AS raw_contract_rows
                """
                if has_all("open", "high", "low", "close", "volume", "vwap", "bar_interval_start_ts")
                else "0 AS raw_contract_rows"
            )
            technical_indicator_expr = (
                """
                    SUM(CASE
                        WHEN ema_12 IS NOT NULL
                         AND ema_26 IS NOT NULL
                         AND macd IS NOT NULL
                         AND rsi_14 IS NOT NULL
                        THEN 1 ELSE 0 END) AS technical_indicator_rows
                """
                if has_all("ema_12", "ema_26", "macd", "rsi_14")
                else "0 AS technical_indicator_rows"
            )
            triple_expr = (
                "SUM(CASE WHEN triple_barrier_label IS NOT NULL THEN 1 ELSE 0 END) AS triple_rows"
                if has_all("triple_barrier_label")
                else "0 AS triple_rows"
            )
            trend_scan_expr = (
                "SUM(CASE WHEN trend_scan_label IS NOT NULL THEN 1 ELSE 0 END) AS trend_scan_rows"
                if has_all("trend_scan_label")
                else "0 AS trend_scan_rows"
            )
            fractional_expr = (
                "SUM(CASE WHEN fractional_diff_zscore_20 IS NOT NULL THEN 1 ELSE 0 END) AS fractional_rows"
                if has_all("fractional_diff_zscore_20")
                else "0 AS fractional_rows"
            )
            vpin_expr = (
                "SUM(CASE WHEN vpin_toxicity_20 IS NOT NULL THEN 1 ELSE 0 END) AS vpin_rows"
                if has_all("vpin_toxicity_20")
                else "0 AS vpin_rows"
            )
            cvd_expr = (
                "SUM(CASE WHEN cumulative_volume_delta IS NOT NULL THEN 1 ELSE 0 END) AS cvd_rows"
                if has_all("cumulative_volume_delta")
                else "0 AS cvd_rows"
            )

            where = "WHERE timeframe = '1m'"
            params: list[str] = []
            if start_date:
                where += " AND substr(bar_timestamp, 1, 10) >= ?"
                params.append(start_date)
            if end_date:
                where += " AND substr(bar_timestamp, 1, 10) <= ?"
                params.append(end_date)

            summary = con.execute(
                f"""
                SELECT
                    COUNT(*) AS rows,
                    COUNT(DISTINCT symbol) AS symbols,
                    COUNT(DISTINCT substr(bar_timestamp, 1, 10)) AS market_dates,
                    MIN(bar_timestamp) AS min_ts,
                    MAX(bar_timestamp) AS max_ts,
                    {raw_contract_expr},
                    {technical_indicator_expr},
                    {triple_expr},
                    {trend_scan_expr},
                    {fractional_expr},
                    {vpin_expr},
                    {cvd_expr}
                FROM bar_pattern_features
                {where}
                """,
                params,
            ).fetchone()

            symbol_triple_expr = (
                "SUM(CASE WHEN triple_barrier_label IS NOT NULL THEN 1 ELSE 0 END) AS triple_rows"
                if has_all("triple_barrier_label")
                else "0 AS triple_rows"
            )
            symbol_trend_expr = (
                "SUM(CASE WHEN trend_scan_label IS NOT NULL THEN 1 ELSE 0 END) AS trend_scan_rows"
                if has_all("trend_scan_label")
                else "0 AS trend_scan_rows"
            )

            top_symbols = con.execute(
                f"""
                SELECT symbol, COUNT(*) AS rows,
                       MIN(bar_timestamp) AS min_ts,
                       MAX(bar_timestamp) AS max_ts
                FROM bar_pattern_features
                {where}
                GROUP BY symbol
                ORDER BY rows DESC, symbol
                LIMIT 12
                """,
                params,
            ).fetchall()

            symbol_rows = con.execute(
                f"""
                SELECT symbol, COUNT(*) AS rows,
                       COUNT(DISTINCT substr(bar_timestamp, 1, 10)) AS market_dates,
                       {symbol_triple_expr},
                       {symbol_trend_expr}
                FROM bar_pattern_features
                {where}
                GROUP BY symbol
                ORDER BY rows DESC, symbol
                """,
                params,
            ).fetchall()

        return {
            "table_exists": True,
            "summary": dict(summary),
            "top_symbols": [dict(row) for row in top_symbols],
            "symbol_rows": [dict(row) for row in symbol_rows],
        }

    def symbol_progress_payload(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        symbols: list[str] | None = None,
    ) -> dict[str, Any] | None:
        if not self.exists():
            return None
        with self._connect() as con:
            if not self._table_exists(con, "bar_pattern_features"):
                return {"table_exists": False}
            columns = self._table_columns(con, "bar_pattern_features")

            def has(name: str) -> bool:
                return name in columns

            triple_expr = (
                "SUM(CASE WHEN triple_barrier_label IS NOT NULL THEN 1 ELSE 0 END) AS triple_rows"
                if has("triple_barrier_label")
                else "0 AS triple_rows"
            )
            trend_expr = (
                "SUM(CASE WHEN trend_scan_label IS NOT NULL THEN 1 ELSE 0 END) AS trend_scan_rows"
                if has("trend_scan_label")
                else "0 AS trend_scan_rows"
            )

            where_tail = "AND timeframe = '1m'"
            if start_date:
                where_tail += " AND substr(bar_timestamp, 1, 10) >= ?"
            if end_date:
                where_tail += " AND substr(bar_timestamp, 1, 10) <= ?"

            if symbols:
                target_symbols = [str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()]
            else:
                target_symbols = [
                    row["symbol"]
                    for row in con.execute(
                        "SELECT DISTINCT symbol FROM bar_pattern_features ORDER BY symbol"
                    ).fetchall()
                ]

            symbol_rows = []
            for symbol in target_symbols:
                params: list[str] = [symbol]
                if start_date:
                    params.append(start_date)
                if end_date:
                    params.append(end_date)
                row = con.execute(
                    f"""
                    SELECT ? AS symbol, COUNT(*) AS rows,
                           COUNT(DISTINCT substr(bar_timestamp, 1, 10)) AS market_dates,
                           {triple_expr},
                           {trend_expr}
                    FROM bar_pattern_features
                    WHERE symbol = ?
                    {where_tail}
                    """,
                    [symbol, *params],
                ).fetchone()
                symbol_rows.append(dict(row))
        return {
            "table_exists": True,
            "symbol_rows": [dict(row) for row in symbol_rows],
        }

    def symbol_coverage_summary(
        self,
        *,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        normalized_symbols = [
            str(symbol).upper().strip()
            for symbol in symbols
            if str(symbol).strip()
        ]
        if not normalized_symbols:
            return {}
        if not self.exists():
            return {
                symbol: {"rows": 0, "trading_days": 0, "coverage_status": "missing_db"}
                for symbol in normalized_symbols
            }

        placeholders = ",".join("?" for _ in normalized_symbols)
        try:
            with self._connect() as con:
                if not self._table_exists(con, "bar_pattern_features"):
                    return {
                        symbol: {
                            "rows": 0,
                            "trading_days": 0,
                            "coverage_status": "missing_bar_pattern_features",
                        }
                        for symbol in normalized_symbols
                    }
                columns = self._table_columns(con, "bar_pattern_features")
                timeframe_filter = "AND timeframe = '1m'" if "timeframe" in columns else ""
                rows = con.execute(
                    f"""
                    SELECT
                        symbol,
                        COUNT(*) AS rows,
                        COUNT(DISTINCT substr(bar_timestamp, 1, 10)) AS trading_days,
                        MIN(substr(bar_timestamp, 1, 10)) AS first_date,
                        MAX(substr(bar_timestamp, 1, 10)) AS last_date
                    FROM bar_pattern_features
                    WHERE symbol IN ({placeholders})
                      {timeframe_filter}
                    GROUP BY symbol
                    """,
                    normalized_symbols,
                ).fetchall()
        except Exception as exc:
            return {
                symbol: {
                    "rows": 0,
                    "trading_days": 0,
                    "coverage_status": f"coverage_query_failed:{type(exc).__name__}",
                }
                for symbol in normalized_symbols
            }

        observed = {
            str(row["symbol"]).upper(): {
                "rows": int(row["rows"] or 0),
                "trading_days": int(row["trading_days"] or 0),
                "first_date": row["first_date"],
                "last_date": row["last_date"],
                "coverage_status": "observed",
            }
            for row in rows
        }
        return {
            symbol: observed.get(
                symbol,
                {"rows": 0, "trading_days": 0, "coverage_status": "no_rows"},
            )
            for symbol in normalized_symbols
        }

    def direct_bar_pattern_rows(
        self,
        *,
        symbols: list[str],
        label_column: str,
        wanted_columns: list[str],
        per_symbol_limit: int,
        total_limit: int,
    ) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self._connect() as con:
            if not self._table_exists(con, "bar_pattern_features"):
                return []
            columns = self._table_columns(con, "bar_pattern_features")
            if label_column not in columns:
                return []
            select_cols = [column for column in wanted_columns if column in columns]
            if not select_cols:
                return []
            select_sql = ", ".join(select_cols)
            for symbol in symbols:
                fetched = con.execute(
                    f"""
                    SELECT {select_sql}
                    FROM bar_pattern_features
                    WHERE symbol = ?
                      AND timeframe = '1m'
                      AND {label_column} IS NOT NULL
                    ORDER BY bar_timestamp DESC
                    LIMIT ?
                    """,
                    (str(symbol).upper().strip(), int(per_symbol_limit)),
                ).fetchall()
                for row in fetched:
                    item = dict(row)
                    item["timestamp"] = item.get("bar_timestamp")
                    rows.append(item)
                if len(rows) >= total_limit:
                    return rows[:total_limit]
        return rows
