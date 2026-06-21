"""Repository quality scans for historical bar-pattern features."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from db import DB_PATH, get_read_connection
from symbols_config import APPROVED_SYMBOLS_LIST


class HistoricalBarQualityRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def exists(self) -> bool:
        return self.db_path.exists()

    def _connect(self):
        return get_read_connection(self.db_path)

    @staticmethod
    def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
        return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}

    @staticmethod
    def _index_exists(con: sqlite3.Connection, table: str, index_name: str) -> bool:
        return any(
            str(row["name"]) == index_name
            for row in con.execute(f"PRAGMA index_list({table})").fetchall()
        )

    @staticmethod
    def _count_expr(condition: str, alias: str) -> str:
        return f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) AS {alias}"

    @staticmethod
    def _exclusive_next_day(day: str) -> str:
        return (date.fromisoformat(day) + timedelta(days=1)).isoformat()

    def quality_payload(
        self,
        *,
        readiness_feature_columns: tuple[str, ...],
        current_feature_version_aliases: tuple[str, ...],
        start_date: str | None,
        end_date: str | None,
        include_duplicate_scan: bool = False,
        symbols: list[str] | None = None,
        symbol_limit: int = 0,
        quality_mode: str = "sample",
        sample_rows_per_symbol: int = 2000,
    ) -> dict[str, Any]:
        if not self.exists():
            return {"table_exists": False, "reason": "missing_db"}
        with self._connect() as con:
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bar_pattern_features'"
            ).fetchone()
            if not exists:
                return {"table_exists": False, "reason": "missing_bar_pattern_features"}
            columns = self._table_columns(con, "bar_pattern_features")
            table_ref = (
                "bar_pattern_features INDEXED BY idx_bar_pattern_features_symbol_ts"
                if self._index_exists(
                    con, "bar_pattern_features", "idx_bar_pattern_features_symbol_ts"
                )
                else "bar_pattern_features"
            )

            selected_symbols = [
                str(symbol).upper().strip()
                for symbol in (symbols or APPROVED_SYMBOLS_LIST)
                if str(symbol).strip()
            ]
            if symbol_limit > 0:
                selected_symbols = selected_symbols[:symbol_limit]

            where = ["symbol = ?"]
            if "timeframe" in columns:
                where.append("timeframe = '1m'")
            if "feature_version" in columns:
                where.append(
                    "feature_version IN ("
                    + ", ".join("?" for _ in current_feature_version_aliases)
                    + ")"
                )
            if start_date:
                where.append("bar_timestamp >= ?")
            if end_date:
                where.append("bar_timestamp < ?")
            where_sql = " AND ".join(where)

            required_price_cols = {"open", "high", "low", "close", "volume"}
            if required_price_cols <= columns:
                null_contract_expr = self._count_expr(
                    "open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume IS NULL",
                    "null_ohlcv_rows",
                )
                invalid_price_expr = self._count_expr(
                    "high < low OR open < low OR open > high OR close < low OR close > high",
                    "invalid_price_rows",
                )
                zero_volume_expr = self._count_expr("volume <= 0", "zero_volume_rows")
            else:
                null_contract_expr = "0 AS null_ohlcv_rows"
                invalid_price_expr = "0 AS invalid_price_rows"
                zero_volume_expr = "0 AS zero_volume_rows"

            timeframe_group = "timeframe" if "timeframe" in columns else "'1m'"
            feature_version_group = "feature_version" if "feature_version" in columns else "''"
            present_columns = [column for column in readiness_feature_columns if column in columns]
            missing_exprs = [
                f"SUM(CASE WHEN {column} IS NULL THEN 1 ELSE 0 END) AS missing_{idx}"
                for idx, column in enumerate(present_columns)
            ]
            label_exprs = []
            for alias, column in (
                ("triple_rows", "triple_barrier_label"),
                ("trend_scan_rows", "trend_scan_label"),
                ("fractional_rows", "fractional_diff_zscore_20"),
                ("vpin_rows", "vpin_toxicity_20"),
                ("cvd_rows", "cumulative_volume_delta"),
            ):
                if column in columns:
                    label_exprs.append(
                        f"SUM(CASE WHEN {column} IS NOT NULL THEN 1 ELSE 0 END) AS {alias}"
                    )
                else:
                    label_exprs.append(f"0 AS {alias}")

            duplicate_rows: int | None = None
            total_rows = 0
            observed_symbols = 0
            market_date_count = 0
            first_date = None
            last_date = None
            null_ohlcv_rows = 0
            invalid_price_rows = 0
            zero_volume_rows = 0
            missing_totals = {idx: 0 for idx in range(len(present_columns))}
            label_totals = {
                "triple_rows": 0,
                "trend_scan_rows": 0,
                "fractional_rows": 0,
                "vpin_rows": 0,
                "cvd_rows": 0,
            }

            select_parts = [
                "COUNT(*) AS rows",
                "COUNT(DISTINCT substr(bar_timestamp, 1, 10)) AS market_dates",
                "MIN(substr(bar_timestamp, 1, 10)) AS first_date",
                "MAX(substr(bar_timestamp, 1, 10)) AS last_date",
                null_contract_expr,
                invalid_price_expr,
                zero_volume_expr,
                *label_exprs,
                *missing_exprs,
            ]

            quality_mode = quality_mode if quality_mode in {"sample", "full"} else "sample"
            sample_rows_per_symbol = max(1, int(sample_rows_per_symbol or 2000))

            for symbol in selected_symbols:
                params: list[Any] = [symbol]
                if "feature_version" in columns:
                    params.extend(current_feature_version_aliases)
                if start_date:
                    params.append(start_date)
                if end_date:
                    params.append(self._exclusive_next_day(end_date))
                if quality_mode == "sample":
                    from_sql = (
                        f"(SELECT * FROM {table_ref} "
                        f"WHERE {where_sql} "
                        f"ORDER BY bar_timestamp DESC "
                        f"LIMIT {sample_rows_per_symbol})"
                    )
                    query_where_sql = "1=1"
                else:
                    from_sql = table_ref
                    query_where_sql = where_sql
                row = con.execute(
                    f"""
                    SELECT {", ".join(select_parts)}
                    FROM {from_sql}
                    WHERE {query_where_sql}
                    """,
                    params,
                ).fetchone()
                rows_for_symbol = int(row["rows"] or 0)
                if rows_for_symbol <= 0:
                    continue
                observed_symbols += 1
                total_rows += rows_for_symbol
                market_date_count = max(market_date_count, int(row["market_dates"] or 0))
                null_ohlcv_rows += int(row["null_ohlcv_rows"] or 0)
                invalid_price_rows += int(row["invalid_price_rows"] or 0)
                zero_volume_rows += int(row["zero_volume_rows"] or 0)
                for key in label_totals:
                    label_totals[key] += int(row[key] or 0)
                for idx in range(len(present_columns)):
                    missing_totals[idx] += int(row[f"missing_{idx}"] or 0)
                if row["first_date"]:
                    first_date = (
                        min(first_date, row["first_date"]) if first_date else row["first_date"]
                    )
                if row["last_date"]:
                    last_date = max(last_date, row["last_date"]) if last_date else row["last_date"]
                if include_duplicate_scan:
                    duplicates = con.execute(
                        f"""
                        SELECT COALESCE(SUM(extra_rows), 0) AS duplicate_rows
                        FROM (
                            SELECT COUNT(*) - 1 AS extra_rows
                            FROM {from_sql}
                            WHERE {query_where_sql}
                            GROUP BY symbol, bar_timestamp, {timeframe_group}, {feature_version_group}
                            HAVING COUNT(*) > 1
                        )
                        """,
                        params,
                    ).fetchone()
                    duplicate_rows = int(duplicate_rows or 0) + int(
                        duplicates["duplicate_rows"] or 0
                    )

            summary = {
                "rows": total_rows,
                "symbols": observed_symbols,
                "market_dates": market_date_count,
                "first_date": first_date,
                "last_date": last_date,
                "null_ohlcv_rows": null_ohlcv_rows,
                "invalid_price_rows": invalid_price_rows,
                "zero_volume_rows": zero_volume_rows,
                **label_totals,
            }

            feature_nulls: list[dict[str, Any]] = []
            for idx, column in enumerate(readiness_feature_columns):
                if column not in columns:
                    feature_nulls.append(
                        {
                            "feature": column,
                            "present": False,
                            "missing_rows": total_rows,
                            "missing_pct": 100.0 if total_rows else 0.0,
                        }
                    )
                    continue
                present_idx = present_columns.index(column)
                missing = int(missing_totals.get(present_idx, 0))
                feature_nulls.append(
                    {
                        "feature": column,
                        "present": True,
                        "missing_rows": missing,
                        "missing_pct": (
                            round(float(missing) / float(total_rows) * 100.0, 2)
                            if total_rows
                            else 0.0
                        ),
                    }
                )

        return {
            "table_exists": True,
            "summary": summary,
            "duplicate_rows": duplicate_rows,
            "duplicate_scan": "included" if include_duplicate_scan else "skipped",
            "feature_nulls": feature_nulls,
            "symbols_scanned": selected_symbols,
            "symbol_scan_limited": bool(
                symbol_limit > 0 and len(selected_symbols) < len(symbols or APPROVED_SYMBOLS_LIST)
            ),
            "quality_mode": quality_mode,
            "sample_rows_per_symbol": sample_rows_per_symbol if quality_mode == "sample" else None,
        }
