"""Read-only training rows from historical bar pattern features."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH
from services.bar_pattern_feature_service import BAR_PATTERN_FEATURE_VERSION
from symbols_config import APPROVED_SYMBOLS_LIST

CURRENT_FEATURE_VERSION_ALIASES = (BAR_PATTERN_FEATURE_VERSION, "v4")


HISTORICAL_BAR_TRAINING_COLUMNS = (
    "symbol",
    "bar_timestamp",
    "feature_version",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "sma_20",
    "bollinger_upper_20",
    "bollinger_lower_20",
    "bollinger_width_20_pct",
    "bollinger_percent_b_20",
    "rolling_volatility_20_pct",
    "day_of_week",
    "minute_of_day",
    "ema_12",
    "ema_26",
    "ema_200",
    "price_vs_ema_200_pct",
    "closes_above_ema_200_5",
    "closes_below_ema_200_5",
    "macd",
    "macd_signal",
    "macd_histogram",
    "macd_histogram_pct",
    "macd_bullish_cross",
    "macd_bearish_cross",
    "macd_bearish_divergence",
    "ema200_macd_reversal_score",
    "rsi_14",
    "candle_body_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "upper_lower_wick_ratio",
    "close_location",
    "range_atr_ratio",
    "atr_20_pct",
    "volume_ratio_20",
    "pressure_return_3",
    "pressure_return_8",
    "volume_weighted_pressure_3",
    "volume_delta",
    "institutional_volume_delta",
    "cumulative_volume_delta",
    "cvd_price_corr_20",
    "vpin_toxicity_20",
    "fractional_diff_close_045",
    "fractional_diff_zscore_20",
    "bid_ask_spread_pct",
    "slippage_estimate_pct",
    "execution_cost_estimate_pct",
    "liquidity_sweep_risk",
    "trend_scan_label",
    "trend_scan_tstat",
    "trend_scan_bars",
    "trend_scan_return_pct",
    "pattern_label",
    "pattern_score",
    "opportunity_action",
    "opportunity_quality",
    "long_opportunity_score",
    "sell_opportunity_score",
    "triple_barrier_label",
    "triple_barrier_reason",
    "triple_barrier_bars_to_event",
    "triple_barrier_profit_pct",
    "triple_barrier_stop_pct",
)


def _connect_ro(db_path: Path | str):
    con = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def _index_exists(con: sqlite3.Connection, table: str, index_name: str) -> bool:
    return any(
        str(row["name"]) == index_name
        for row in con.execute(f"PRAGMA index_list({table})").fetchall()
    )


def _expr(columns: set[str], column: str) -> str:
    if column in columns:
        return column
    return f"NULL AS {column}"


def fetch_historical_bar_training_rows(
    *,
    db_path: Path | str = DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    symbol: str | None = None,
    label_target: str = "triple_barrier_label",
    limit: int = 50000,
    rows_per_symbol: int = 0,
) -> list[dict[str, Any]]:
    """Fetch current-version historical bar rows for observe-only ML training.

    This deliberately does not join runtime decisions or account state. The
    historical-bar model is an evidence layer over completed Polygon/Alpaca bar
    data and cannot affect live authority by itself.
    """
    path = Path(db_path)
    if not path.exists():
        return []
    with _connect_ro(path) as con:
        columns = _table_columns(con, "bar_pattern_features")
        if not columns:
            return []
        if label_target not in columns:
            return []
        table_ref = (
            "bar_pattern_features INDEXED BY idx_bar_pattern_features_symbol_ts"
            if _index_exists(con, "bar_pattern_features", "idx_bar_pattern_features_symbol_ts")
            else "bar_pattern_features"
        )

        where = ["timeframe = '1m'" if "timeframe" in columns else "1=1"]
        params: list[Any] = []
        if "feature_version" in columns:
            where.append(
                "feature_version IN ("
                + ", ".join("?" for _ in CURRENT_FEATURE_VERSION_ALIASES)
                + ")"
            )
            params.extend(CURRENT_FEATURE_VERSION_ALIASES)
        where.append(f"{label_target} IS NOT NULL")
        if start_date:
            where.append("bar_timestamp >= ?")
            params.append(start_date)
        if end_date:
            where.append("bar_timestamp < date(?, '+1 day')")
            params.append(end_date)
        if symbol and not (rows_per_symbol and rows_per_symbol > 0):
            where.append("symbol = ?")
            params.append(symbol.upper().strip())

        select_columns = ", ".join(_expr(columns, col) for col in HISTORICAL_BAR_TRAINING_COLUMNS)
        limit_sql = ""
        if limit and limit > 0:
            limit_sql = "LIMIT ?"
        if rows_per_symbol and rows_per_symbol > 0:
            selected_symbols = [symbol.upper().strip()] if symbol else APPROVED_SYMBOLS_LIST
            combined: list[dict[str, Any]] = []
            for selected_symbol in selected_symbols:
                symbol_where = [*where, "symbol = ?"]
                symbol_params = [*params, selected_symbol, int(rows_per_symbol)]
                symbol_rows = con.execute(
                    f"""
                    SELECT {select_columns}
                    FROM {table_ref}
                    WHERE {" AND ".join(symbol_where)}
                    ORDER BY bar_timestamp ASC, rowid ASC
                    LIMIT ?
                    """,
                    symbol_params,
                ).fetchall()
                for idx, row in enumerate(symbol_rows, start=1):
                    item = dict(row)
                    item["symbol_row_number"] = idx
                    combined.append(item)
            combined.sort(
                key=lambda row: (
                    str(row.get("bar_timestamp") or ""),
                    str(row.get("symbol") or ""),
                )
            )
            if limit and limit > 0:
                combined = combined[: int(limit)]
            return combined
        else:
            query_params = [*params]
            if limit_sql:
                query_params.append(int(limit))
            rows = con.execute(
                f"""
                SELECT {select_columns}
                FROM {table_ref}
                WHERE {" AND ".join(where)}
                ORDER BY bar_timestamp ASC, symbol ASC, rowid ASC
                {limit_sql}
                """,
                query_params,
            ).fetchall()
    return [dict(row) for row in rows]
