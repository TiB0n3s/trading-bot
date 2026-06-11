"""Persistence for observe-only advanced per-bar learning rows."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class BarPatternFeatureRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def _table_exists(self, con) -> bool:
        row = con.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'bar_pattern_features'
            """
        ).fetchone()
        return row is not None

    def _table_columns(self, con) -> set[str]:
        if not self._table_exists(con):
            return set()
        return {
            str(row["name"])
            for row in con.execute("PRAGMA table_info(bar_pattern_features)").fetchall()
        }

    def count_existing_1m_rows(
        self,
        *,
        symbol: str,
        start_ts: str,
        end_exclusive_ts: str,
    ) -> int:
        with get_connection(self.db_path) as con:
            if not self._table_exists(con):
                return 0
            row = con.execute(
                """
                SELECT COUNT(*) AS rows
                FROM bar_pattern_features
                WHERE symbol = ?
                  AND timeframe = '1m'
                  AND bar_timestamp >= ?
                  AND bar_timestamp < ?
                """,
                (symbol, start_ts, end_exclusive_ts),
            ).fetchone()
            return int(row["rows"] or 0) if row else 0

    def latest_webull_rsi_snapshot(self, symbol: str) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").upper().strip()
        if not normalized_symbol:
            return {"found": False, "symbol": "", "reason": "symbol_required"}
        with get_connection(self.db_path) as con:
            if not self._table_exists(con):
                return {
                    "found": False,
                    "symbol": normalized_symbol,
                    "reason": "bar_pattern_features_missing",
                }
            columns = self._table_columns(con)
            required = {
                "symbol",
                "bar_timestamp",
                "timeframe",
                "close",
                "webull_rsi_14",
                "webull_rsi_zone",
                "webull_rsi_exit_signal",
                "webull_rsi_bearish_divergence",
            }
            missing = sorted(required - columns)
            if missing:
                return {
                    "found": False,
                    "symbol": normalized_symbol,
                    "reason": f"missing_columns:{','.join(missing)}",
                }
            row = con.execute(
                """
                SELECT
                    bar_timestamp,
                    timeframe,
                    close,
                    webull_rsi_14,
                    webull_rsi_zone,
                    webull_rsi_exit_signal,
                    webull_rsi_bearish_divergence
                FROM bar_pattern_features
                WHERE symbol = ?
                  AND webull_rsi_14 IS NOT NULL
                ORDER BY bar_timestamp DESC
                LIMIT 1
                """,
                (normalized_symbol,),
            ).fetchone()
        if not row:
            return {
                "found": False,
                "symbol": normalized_symbol,
                "reason": "no_persisted_webull_rsi_rows",
            }
        return {
            "found": True,
            "symbol": normalized_symbol,
            "bar_timestamp": row["bar_timestamp"],
            "timeframe": row["timeframe"],
            "close": row["close"],
            "webull_rsi_14": row["webull_rsi_14"],
            "webull_rsi_zone": row["webull_rsi_zone"],
            "webull_rsi_exit_signal": row["webull_rsi_exit_signal"],
            "webull_rsi_bearish_divergence": row["webull_rsi_bearish_divergence"],
        }

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS bar_pattern_features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    bar_timestamp TEXT NOT NULL,
                    bar_source TEXT,
                    bar_feed TEXT,
                    bar_adjusted INTEGER,
                    bar_trade_count REAL,
                    bar_interval_start_ts TEXT,
                    bar_interval_semantics TEXT,
                    timeframe TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    vwap REAL,
                    sma_20 REAL,
                    bollinger_upper_20 REAL,
                    bollinger_lower_20 REAL,
                    bollinger_width_20_pct REAL,
                    bollinger_percent_b_20 REAL,
                    rolling_volatility_20_pct REAL,
                    day_of_week INTEGER,
                    minute_of_day INTEGER,
                    day_of_month INTEGER,
                    week_of_month INTEGER,
                    month_end_proximity_days INTEGER,
                    monday_volatility_flag INTEGER,
                    friday_rebalance_flag INTEGER,
                    prior_session_return_pct REAL,
                    prior_5_session_return_pct REAL,
                    session_phase TEXT,
                    bid_price REAL,
                    ask_price REAL,
                    bid_ask_spread_pct REAL,
                    slippage_estimate_pct REAL,
                    execution_cost_estimate_pct REAL,
                    liquidity_zone_label TEXT,
                    liquidity_sweep_risk REAL,
                    ema_12 REAL,
                    ema_26 REAL,
                    ema_200 REAL,
                    price_vs_ema_200_pct REAL,
                    closes_above_ema_200_5 INTEGER,
                    closes_below_ema_200_5 INTEGER,
                    macd REAL,
                    macd_signal REAL,
                    macd_histogram REAL,
                    macd_histogram_pct REAL,
                    macd_bullish_cross INTEGER,
                    macd_bearish_cross INTEGER,
                    macd_histogram_reversal TEXT,
                    macd_bearish_divergence INTEGER,
                    ema200_macd_reversal_signal TEXT,
                    ema200_macd_reversal_score REAL,
                    rsi_14 REAL,
                    webull_rsi_14 REAL,
                    webull_rsi_zone TEXT,
                    webull_rsi_exit_signal TEXT,
                    webull_rsi_bearish_divergence INTEGER,
                    efi REAL,
                    efi_ema_13 REAL,
                    efi_slope_3 REAL,
                    efi_zscore_20 REAL,
                    pvt REAL,
                    pvt_slope_5 REAL,
                    pvt_new_high_30 INTEGER,
                    price_return_5 REAL,
                    price_vs_sma_20_pct REAL,
                    candle_body_pct REAL,
                    upper_wick_pct REAL,
                    lower_wick_pct REAL,
                    upper_lower_wick_ratio REAL,
                    close_location REAL,
                    range_atr_ratio REAL,
                    atr_20_pct REAL,
                    volume_ratio_20 REAL,
                    pressure_return_3 REAL,
                    pressure_return_8 REAL,
                    volume_weighted_pressure_3 REAL,
                    trade_direction REAL,
                    volume_delta REAL,
                    institutional_volume_delta REAL,
                    cumulative_volume_delta REAL,
                    cvd_price_corr_20 REAL,
                    cvd_divergence_label TEXT,
                    vpin_toxicity_20 REAL,
                    fractional_diff_close_045 REAL,
                    fractional_diff_zscore_20 REAL,
                    trend_scan_label INTEGER,
                    trend_scan_tstat REAL,
                    trend_scan_bars INTEGER,
                    trend_scan_return_pct REAL,
                    trend_scan_reason TEXT,
                    triple_barrier_label INTEGER,
                    triple_barrier_reason TEXT,
                    triple_barrier_bars_to_event INTEGER,
                    triple_barrier_profit_pct REAL,
                    triple_barrier_stop_pct REAL,
                    breakout_20 INTEGER,
                    pattern_label TEXT,
                    pattern_score REAL,
                    opportunity_action TEXT,
                    opportunity_quality TEXT,
                    long_opportunity_score REAL,
                    sell_opportunity_score REAL,
                    forward_return_pct REAL,
                    forward_mfe_pct REAL,
                    forward_mae_pct REAL,
                    horizon_bars INTEGER,
                    feature_version TEXT NOT NULL,
                    runtime_effect TEXT NOT NULL,
                    feature_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, bar_timestamp, timeframe, feature_version)
                )
                """
            )
            self._ensure_column(con, "opportunity_action", "TEXT")
            self._ensure_column(con, "opportunity_quality", "TEXT")
            self._ensure_column(con, "long_opportunity_score", "REAL")
            self._ensure_column(con, "sell_opportunity_score", "REAL")
            self._ensure_column(con, "bar_source", "TEXT")
            self._ensure_column(con, "bar_feed", "TEXT")
            self._ensure_column(con, "bar_adjusted", "INTEGER")
            self._ensure_column(con, "bar_trade_count", "REAL")
            self._ensure_column(con, "bar_interval_start_ts", "TEXT")
            self._ensure_column(con, "bar_interval_semantics", "TEXT")
            self._ensure_column(con, "open", "REAL")
            self._ensure_column(con, "high", "REAL")
            self._ensure_column(con, "low", "REAL")
            self._ensure_column(con, "vwap", "REAL")
            self._ensure_column(con, "sma_20", "REAL")
            self._ensure_column(con, "bollinger_upper_20", "REAL")
            self._ensure_column(con, "bollinger_lower_20", "REAL")
            self._ensure_column(con, "bollinger_width_20_pct", "REAL")
            self._ensure_column(con, "bollinger_percent_b_20", "REAL")
            self._ensure_column(con, "rolling_volatility_20_pct", "REAL")
            self._ensure_column(con, "day_of_week", "INTEGER")
            self._ensure_column(con, "minute_of_day", "INTEGER")
            self._ensure_column(con, "day_of_month", "INTEGER")
            self._ensure_column(con, "week_of_month", "INTEGER")
            self._ensure_column(con, "month_end_proximity_days", "INTEGER")
            self._ensure_column(con, "monday_volatility_flag", "INTEGER")
            self._ensure_column(con, "friday_rebalance_flag", "INTEGER")
            self._ensure_column(con, "prior_session_return_pct", "REAL")
            self._ensure_column(con, "prior_5_session_return_pct", "REAL")
            self._ensure_column(con, "session_phase", "TEXT")
            self._ensure_column(con, "bid_price", "REAL")
            self._ensure_column(con, "ask_price", "REAL")
            self._ensure_column(con, "bid_ask_spread_pct", "REAL")
            self._ensure_column(con, "slippage_estimate_pct", "REAL")
            self._ensure_column(con, "execution_cost_estimate_pct", "REAL")
            self._ensure_column(con, "liquidity_zone_label", "TEXT")
            self._ensure_column(con, "liquidity_sweep_risk", "REAL")
            self._ensure_column(con, "ema_12", "REAL")
            self._ensure_column(con, "ema_26", "REAL")
            self._ensure_column(con, "ema_200", "REAL")
            self._ensure_column(con, "price_vs_ema_200_pct", "REAL")
            self._ensure_column(con, "closes_above_ema_200_5", "INTEGER")
            self._ensure_column(con, "closes_below_ema_200_5", "INTEGER")
            self._ensure_column(con, "macd", "REAL")
            self._ensure_column(con, "macd_signal", "REAL")
            self._ensure_column(con, "macd_histogram", "REAL")
            self._ensure_column(con, "macd_histogram_pct", "REAL")
            self._ensure_column(con, "macd_bullish_cross", "INTEGER")
            self._ensure_column(con, "macd_bearish_cross", "INTEGER")
            self._ensure_column(con, "macd_histogram_reversal", "TEXT")
            self._ensure_column(con, "macd_bearish_divergence", "INTEGER")
            self._ensure_column(con, "ema200_macd_reversal_signal", "TEXT")
            self._ensure_column(con, "ema200_macd_reversal_score", "REAL")
            self._ensure_column(con, "rsi_14", "REAL")
            self._ensure_column(con, "webull_rsi_14", "REAL")
            self._ensure_column(con, "webull_rsi_zone", "TEXT")
            self._ensure_column(con, "webull_rsi_exit_signal", "TEXT")
            self._ensure_column(con, "webull_rsi_bearish_divergence", "INTEGER")
            self._ensure_column(con, "candle_body_pct", "REAL")
            self._ensure_column(con, "upper_wick_pct", "REAL")
            self._ensure_column(con, "lower_wick_pct", "REAL")
            self._ensure_column(con, "upper_lower_wick_ratio", "REAL")
            self._ensure_column(con, "close_location", "REAL")
            self._ensure_column(con, "range_atr_ratio", "REAL")
            self._ensure_column(con, "atr_20_pct", "REAL")
            self._ensure_column(con, "volume_ratio_20", "REAL")
            self._ensure_column(con, "pressure_return_3", "REAL")
            self._ensure_column(con, "pressure_return_8", "REAL")
            self._ensure_column(con, "volume_weighted_pressure_3", "REAL")
            self._ensure_column(con, "trade_direction", "REAL")
            self._ensure_column(con, "volume_delta", "REAL")
            self._ensure_column(con, "institutional_volume_delta", "REAL")
            self._ensure_column(con, "cumulative_volume_delta", "REAL")
            self._ensure_column(con, "cvd_price_corr_20", "REAL")
            self._ensure_column(con, "cvd_divergence_label", "TEXT")
            self._ensure_column(con, "vpin_toxicity_20", "REAL")
            self._ensure_column(con, "fractional_diff_close_045", "REAL")
            self._ensure_column(con, "fractional_diff_zscore_20", "REAL")
            self._ensure_column(con, "trend_scan_label", "INTEGER")
            self._ensure_column(con, "trend_scan_tstat", "REAL")
            self._ensure_column(con, "trend_scan_bars", "INTEGER")
            self._ensure_column(con, "trend_scan_return_pct", "REAL")
            self._ensure_column(con, "trend_scan_reason", "TEXT")
            self._ensure_column(con, "triple_barrier_label", "INTEGER")
            self._ensure_column(con, "triple_barrier_reason", "TEXT")
            self._ensure_column(con, "triple_barrier_bars_to_event", "INTEGER")
            self._ensure_column(con, "triple_barrier_profit_pct", "REAL")
            self._ensure_column(con, "triple_barrier_stop_pct", "REAL")
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bar_pattern_features_symbol_ts
                ON bar_pattern_features(symbol, bar_timestamp)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bar_pattern_features_timeframe_ts
                ON bar_pattern_features(timeframe, bar_timestamp)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bar_pattern_features_ts
                ON bar_pattern_features(bar_timestamp)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bar_pattern_features_label
                ON bar_pattern_features(pattern_label, bar_timestamp)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bar_pattern_features_opportunity
                ON bar_pattern_features(opportunity_action, opportunity_quality, bar_timestamp)
                """
            )

    def _ensure_column(self, con, column: str, column_type: str) -> None:
        columns = {
            str(row["name"])
            for row in con.execute("PRAGMA table_info(bar_pattern_features)").fetchall()
        }
        if column not in columns:
            con.execute(f"ALTER TABLE bar_pattern_features ADD COLUMN {column} {column_type}")

    def upsert_many(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.init_table()
        with get_connection(self.db_path) as con:
            con.executemany(
                """
                INSERT INTO bar_pattern_features (
                    symbol, bar_timestamp, bar_source, bar_feed, bar_adjusted,
                    bar_trade_count, bar_interval_start_ts, bar_interval_semantics,
                    timeframe, open, high, low, close, volume, vwap,
                    sma_20, bollinger_upper_20, bollinger_lower_20,
                    bollinger_width_20_pct, bollinger_percent_b_20,
                    rolling_volatility_20_pct, day_of_week, minute_of_day,
                    day_of_month, week_of_month, month_end_proximity_days,
                    monday_volatility_flag, friday_rebalance_flag,
                    prior_session_return_pct, prior_5_session_return_pct,
                    session_phase, bid_price, ask_price, bid_ask_spread_pct,
                    slippage_estimate_pct, execution_cost_estimate_pct,
                    liquidity_zone_label, liquidity_sweep_risk, ema_12,
                    ema_26, ema_200, price_vs_ema_200_pct,
                    closes_above_ema_200_5, closes_below_ema_200_5,
                    macd, macd_signal, macd_histogram, macd_histogram_pct,
                    macd_bullish_cross, macd_bearish_cross,
                    macd_histogram_reversal, macd_bearish_divergence,
                    ema200_macd_reversal_signal, ema200_macd_reversal_score, rsi_14,
                    webull_rsi_14, webull_rsi_zone, webull_rsi_exit_signal,
                    webull_rsi_bearish_divergence,
                    efi, efi_ema_13, efi_slope_3, efi_zscore_20,
                    pvt, pvt_slope_5, pvt_new_high_30,
                    price_return_5, price_vs_sma_20_pct, breakout_20,
                    candle_body_pct, upper_wick_pct, lower_wick_pct,
                    upper_lower_wick_ratio, close_location, range_atr_ratio,
                    atr_20_pct, volume_ratio_20, pressure_return_3,
                    pressure_return_8, volume_weighted_pressure_3,
                    trade_direction, volume_delta, institutional_volume_delta,
                    cumulative_volume_delta, cvd_price_corr_20,
                    cvd_divergence_label, vpin_toxicity_20,
                    fractional_diff_close_045, fractional_diff_zscore_20,
                    trend_scan_label, trend_scan_tstat, trend_scan_bars,
                    trend_scan_return_pct, trend_scan_reason,
                    triple_barrier_label, triple_barrier_reason,
                    triple_barrier_bars_to_event, triple_barrier_profit_pct,
                    triple_barrier_stop_pct,
                    pattern_label, pattern_score,
                    opportunity_action, opportunity_quality,
                    long_opportunity_score, sell_opportunity_score,
                    forward_return_pct, forward_mfe_pct, forward_mae_pct,
                    horizon_bars, feature_version, runtime_effect, feature_json
                ) VALUES (
                    :symbol, :bar_timestamp, :bar_source, :bar_feed, :bar_adjusted,
                    :bar_trade_count, :bar_interval_start_ts,
                    :bar_interval_semantics, :timeframe, :open, :high, :low,
                    :close, :volume, :vwap, :sma_20, :bollinger_upper_20,
                    :bollinger_lower_20, :bollinger_width_20_pct,
                    :bollinger_percent_b_20, :rolling_volatility_20_pct,
                    :day_of_week, :minute_of_day, :day_of_month,
                    :week_of_month, :month_end_proximity_days,
                    :monday_volatility_flag, :friday_rebalance_flag,
                    :prior_session_return_pct, :prior_5_session_return_pct,
                    :session_phase,
                    :bid_price, :ask_price, :bid_ask_spread_pct,
                    :slippage_estimate_pct, :execution_cost_estimate_pct,
                    :liquidity_zone_label, :liquidity_sweep_risk, :ema_12,
                    :ema_26, :ema_200, :price_vs_ema_200_pct,
                    :closes_above_ema_200_5, :closes_below_ema_200_5,
                    :macd, :macd_signal, :macd_histogram, :macd_histogram_pct,
                    :macd_bullish_cross, :macd_bearish_cross,
                    :macd_histogram_reversal, :macd_bearish_divergence,
                    :ema200_macd_reversal_signal, :ema200_macd_reversal_score, :rsi_14,
                    :webull_rsi_14, :webull_rsi_zone, :webull_rsi_exit_signal,
                    :webull_rsi_bearish_divergence,
                    :efi, :efi_ema_13, :efi_slope_3, :efi_zscore_20,
                    :pvt, :pvt_slope_5, :pvt_new_high_30,
                    :price_return_5, :price_vs_sma_20_pct, :breakout_20,
                    :candle_body_pct, :upper_wick_pct, :lower_wick_pct,
                    :upper_lower_wick_ratio, :close_location, :range_atr_ratio,
                    :atr_20_pct, :volume_ratio_20, :pressure_return_3,
                    :pressure_return_8, :volume_weighted_pressure_3,
                    :trade_direction, :volume_delta, :institutional_volume_delta,
                    :cumulative_volume_delta, :cvd_price_corr_20,
                    :cvd_divergence_label, :vpin_toxicity_20,
                    :fractional_diff_close_045, :fractional_diff_zscore_20,
                    :trend_scan_label, :trend_scan_tstat, :trend_scan_bars,
                    :trend_scan_return_pct, :trend_scan_reason,
                    :triple_barrier_label, :triple_barrier_reason,
                    :triple_barrier_bars_to_event, :triple_barrier_profit_pct,
                    :triple_barrier_stop_pct,
                    :pattern_label, :pattern_score,
                    :opportunity_action, :opportunity_quality,
                    :long_opportunity_score, :sell_opportunity_score,
                    :forward_return_pct, :forward_mfe_pct, :forward_mae_pct,
                    :horizon_bars, :feature_version, :runtime_effect, :feature_json
                )
                ON CONFLICT(symbol, bar_timestamp, timeframe, feature_version)
                DO UPDATE SET
                    bar_source = excluded.bar_source,
                    bar_feed = excluded.bar_feed,
                    bar_adjusted = excluded.bar_adjusted,
                    bar_trade_count = excluded.bar_trade_count,
                    bar_interval_start_ts = excluded.bar_interval_start_ts,
                    bar_interval_semantics = excluded.bar_interval_semantics,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    vwap = excluded.vwap,
                    sma_20 = excluded.sma_20,
                    bollinger_upper_20 = excluded.bollinger_upper_20,
                    bollinger_lower_20 = excluded.bollinger_lower_20,
                    bollinger_width_20_pct = excluded.bollinger_width_20_pct,
                    bollinger_percent_b_20 = excluded.bollinger_percent_b_20,
                    rolling_volatility_20_pct = excluded.rolling_volatility_20_pct,
                    day_of_week = excluded.day_of_week,
                    minute_of_day = excluded.minute_of_day,
                    day_of_month = excluded.day_of_month,
                    week_of_month = excluded.week_of_month,
                    month_end_proximity_days = excluded.month_end_proximity_days,
                    monday_volatility_flag = excluded.monday_volatility_flag,
                    friday_rebalance_flag = excluded.friday_rebalance_flag,
                    prior_session_return_pct = excluded.prior_session_return_pct,
                    prior_5_session_return_pct = excluded.prior_5_session_return_pct,
                    session_phase = excluded.session_phase,
                    bid_price = excluded.bid_price,
                    ask_price = excluded.ask_price,
                    bid_ask_spread_pct = excluded.bid_ask_spread_pct,
                    slippage_estimate_pct = excluded.slippage_estimate_pct,
                    execution_cost_estimate_pct = excluded.execution_cost_estimate_pct,
                    liquidity_zone_label = excluded.liquidity_zone_label,
                    liquidity_sweep_risk = excluded.liquidity_sweep_risk,
                    ema_12 = excluded.ema_12,
                    ema_26 = excluded.ema_26,
                    ema_200 = excluded.ema_200,
                    price_vs_ema_200_pct = excluded.price_vs_ema_200_pct,
                    closes_above_ema_200_5 = excluded.closes_above_ema_200_5,
                    closes_below_ema_200_5 = excluded.closes_below_ema_200_5,
                    macd = excluded.macd,
                    macd_signal = excluded.macd_signal,
                    macd_histogram = excluded.macd_histogram,
                    macd_histogram_pct = excluded.macd_histogram_pct,
                    macd_bullish_cross = excluded.macd_bullish_cross,
                    macd_bearish_cross = excluded.macd_bearish_cross,
                    macd_histogram_reversal = excluded.macd_histogram_reversal,
                    macd_bearish_divergence = excluded.macd_bearish_divergence,
                    ema200_macd_reversal_signal = excluded.ema200_macd_reversal_signal,
                    ema200_macd_reversal_score = excluded.ema200_macd_reversal_score,
                    rsi_14 = excluded.rsi_14,
                    webull_rsi_14 = excluded.webull_rsi_14,
                    webull_rsi_zone = excluded.webull_rsi_zone,
                    webull_rsi_exit_signal = excluded.webull_rsi_exit_signal,
                    webull_rsi_bearish_divergence = excluded.webull_rsi_bearish_divergence,
                    efi = excluded.efi,
                    efi_ema_13 = excluded.efi_ema_13,
                    efi_slope_3 = excluded.efi_slope_3,
                    efi_zscore_20 = excluded.efi_zscore_20,
                    pvt = excluded.pvt,
                    pvt_slope_5 = excluded.pvt_slope_5,
                    pvt_new_high_30 = excluded.pvt_new_high_30,
                    price_return_5 = excluded.price_return_5,
                    price_vs_sma_20_pct = excluded.price_vs_sma_20_pct,
                    candle_body_pct = excluded.candle_body_pct,
                    upper_wick_pct = excluded.upper_wick_pct,
                    lower_wick_pct = excluded.lower_wick_pct,
                    upper_lower_wick_ratio = excluded.upper_lower_wick_ratio,
                    close_location = excluded.close_location,
                    range_atr_ratio = excluded.range_atr_ratio,
                    atr_20_pct = excluded.atr_20_pct,
                    volume_ratio_20 = excluded.volume_ratio_20,
                    pressure_return_3 = excluded.pressure_return_3,
                    pressure_return_8 = excluded.pressure_return_8,
                    volume_weighted_pressure_3 = excluded.volume_weighted_pressure_3,
                    trade_direction = excluded.trade_direction,
                    volume_delta = excluded.volume_delta,
                    institutional_volume_delta = excluded.institutional_volume_delta,
                    cumulative_volume_delta = excluded.cumulative_volume_delta,
                    cvd_price_corr_20 = excluded.cvd_price_corr_20,
                    cvd_divergence_label = excluded.cvd_divergence_label,
                    vpin_toxicity_20 = excluded.vpin_toxicity_20,
                    fractional_diff_close_045 = excluded.fractional_diff_close_045,
                    fractional_diff_zscore_20 = excluded.fractional_diff_zscore_20,
                    trend_scan_label = excluded.trend_scan_label,
                    trend_scan_tstat = excluded.trend_scan_tstat,
                    trend_scan_bars = excluded.trend_scan_bars,
                    trend_scan_return_pct = excluded.trend_scan_return_pct,
                    trend_scan_reason = excluded.trend_scan_reason,
                    triple_barrier_label = excluded.triple_barrier_label,
                    triple_barrier_reason = excluded.triple_barrier_reason,
                    triple_barrier_bars_to_event = excluded.triple_barrier_bars_to_event,
                    triple_barrier_profit_pct = excluded.triple_barrier_profit_pct,
                    triple_barrier_stop_pct = excluded.triple_barrier_stop_pct,
                    breakout_20 = excluded.breakout_20,
                    pattern_label = excluded.pattern_label,
                    pattern_score = excluded.pattern_score,
                    opportunity_action = excluded.opportunity_action,
                    opportunity_quality = excluded.opportunity_quality,
                    long_opportunity_score = excluded.long_opportunity_score,
                    sell_opportunity_score = excluded.sell_opportunity_score,
                    forward_return_pct = excluded.forward_return_pct,
                    forward_mfe_pct = excluded.forward_mfe_pct,
                    forward_mae_pct = excluded.forward_mae_pct,
                    horizon_bars = excluded.horizon_bars,
                    runtime_effect = excluded.runtime_effect,
                    feature_json = excluded.feature_json
                """,
                [
                    {
                        **row,
                        "feature_json": json.dumps(
                            row.get("feature_json") or {},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                    for row in rows
                ],
            )
            return len(rows)

    def summary(self, target_date: str, symbol: str | None = None) -> dict[str, Any]:
        self.init_table()
        try:
            start = date.fromisoformat(target_date)
            end_text = (start + timedelta(days=1)).isoformat()
        except Exception:
            end_text = target_date
        params: list[Any] = [target_date, end_text]
        extra = ""
        if symbol:
            extra = " AND symbol = ?"
            params.append(symbol.upper())
        where = "bar_timestamp >= ? AND bar_timestamp < ?"
        with get_connection(self.db_path) as con:
            row = con.execute(
                f"""
                SELECT
                    COUNT(*) AS rows,
                    COUNT(DISTINCT symbol) AS symbols,
                    SUM(CASE
                        WHEN open IS NOT NULL
                         AND high IS NOT NULL
                         AND low IS NOT NULL
                         AND close IS NOT NULL
                         AND volume IS NOT NULL
                         AND vwap IS NOT NULL
                         AND bar_interval_start_ts IS NOT NULL
                        THEN 1 ELSE 0 END) AS rows_with_raw_bar_contract,
                    SUM(CASE WHEN bar_source IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_source,
                    SUM(CASE WHEN bar_adjusted IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_adjustment_flag,
                    SUM(CASE WHEN bar_trade_count IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_trade_count,
                    SUM(CASE WHEN bollinger_percent_b_20 IS NOT NULL AND rolling_volatility_20_pct IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_bollinger_context,
                    SUM(CASE WHEN day_of_week IS NOT NULL AND minute_of_day IS NOT NULL AND session_phase IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_temporal_context,
                    SUM(CASE
                        WHEN bid_ask_spread_pct IS NOT NULL
                          OR slippage_estimate_pct IS NOT NULL
                          OR execution_cost_estimate_pct IS NOT NULL
                          OR liquidity_sweep_risk IS NOT NULL
                        THEN 1 ELSE 0 END) AS rows_with_microstructure_context,
                    SUM(CASE
                        WHEN ema_12 IS NOT NULL
                         AND ema_26 IS NOT NULL
                         AND ema_200 IS NOT NULL
                         AND macd IS NOT NULL
                         AND rsi_14 IS NOT NULL
                         AND webull_rsi_14 IS NOT NULL
                        THEN 1 ELSE 0 END)
                        AS rows_with_technical_indicators,
                    SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_forward_outcome,
                    SUM(CASE WHEN cvd_price_corr_20 IS NOT NULL OR vpin_toxicity_20 IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_order_flow,
                    SUM(CASE WHEN fractional_diff_zscore_20 IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_fractional_memory
                FROM bar_pattern_features
                WHERE {where}
                {extra}
                """,
                params,
            ).fetchone()
            labels = con.execute(
                f"""
                SELECT
                    pattern_label,
                    COUNT(*) AS rows,
                    AVG(forward_return_pct) AS avg_forward_return_pct,
                    AVG(forward_mfe_pct) AS avg_forward_mfe_pct,
                    AVG(forward_mae_pct) AS avg_forward_mae_pct
                FROM bar_pattern_features
                WHERE {where}
                {extra}
                GROUP BY pattern_label
                ORDER BY rows DESC, pattern_label
                """,
                params,
            ).fetchall()
            opportunities = con.execute(
                f"""
                SELECT
                    opportunity_action,
                    opportunity_quality,
                    COUNT(*) AS rows,
                    AVG(long_opportunity_score) AS avg_long_opportunity_score,
                    AVG(sell_opportunity_score) AS avg_sell_opportunity_score,
                    AVG(forward_return_pct) AS avg_forward_return_pct,
                    AVG(forward_mfe_pct) AS avg_forward_mfe_pct,
                    AVG(forward_mae_pct) AS avg_forward_mae_pct
                FROM bar_pattern_features
                WHERE {where}
                {extra}
                GROUP BY opportunity_action, opportunity_quality
                ORDER BY rows DESC, opportunity_action, opportunity_quality
                """,
                params,
            ).fetchall()
            triple_barriers = con.execute(
                f"""
                SELECT
                    triple_barrier_label,
                    COALESCE(triple_barrier_reason, 'unknown') AS triple_barrier_reason,
                    COUNT(*) AS rows,
                    AVG(forward_return_pct) AS avg_forward_return_pct,
                    AVG(forward_mfe_pct) AS avg_forward_mfe_pct,
                    AVG(forward_mae_pct) AS avg_forward_mae_pct,
                    AVG(triple_barrier_bars_to_event) AS avg_bars_to_event
                FROM bar_pattern_features
                WHERE {where}
                {extra}
                  AND triple_barrier_label IS NOT NULL
                GROUP BY triple_barrier_label, triple_barrier_reason
                ORDER BY rows DESC, triple_barrier_label
                """,
                params,
            ).fetchall()
            trend_scans = con.execute(
                f"""
                SELECT
                    trend_scan_label,
                    COALESCE(trend_scan_reason, 'unknown') AS trend_scan_reason,
                    COUNT(*) AS rows,
                    AVG(forward_return_pct) AS avg_forward_return_pct,
                    AVG(forward_mfe_pct) AS avg_forward_mfe_pct,
                    AVG(forward_mae_pct) AS avg_forward_mae_pct,
                    AVG(trend_scan_tstat) AS avg_trend_scan_tstat,
                    AVG(trend_scan_bars) AS avg_trend_scan_bars
                FROM bar_pattern_features
                WHERE {where}
                {extra}
                  AND trend_scan_label IS NOT NULL
                GROUP BY trend_scan_label, trend_scan_reason
                ORDER BY rows DESC, trend_scan_label
                """,
                params,
            ).fetchall()
            cvd_divergences = con.execute(
                f"""
                SELECT
                    COALESCE(cvd_divergence_label, 'unknown') AS cvd_divergence_label,
                    COUNT(*) AS rows,
                    AVG(forward_return_pct) AS avg_forward_return_pct,
                    AVG(forward_mfe_pct) AS avg_forward_mfe_pct,
                    AVG(forward_mae_pct) AS avg_forward_mae_pct,
                    AVG(vpin_toxicity_20) AS avg_vpin_toxicity_20
                FROM bar_pattern_features
                WHERE {where}
                {extra}
                GROUP BY cvd_divergence_label
                ORDER BY rows DESC, cvd_divergence_label
                """,
                params,
            ).fetchall()
        return {
            "rows": int(row["rows"] or 0),
            "symbols": int(row["symbols"] or 0),
            "rows_with_raw_bar_contract": int(row["rows_with_raw_bar_contract"] or 0),
            "rows_with_source": int(row["rows_with_source"] or 0),
            "rows_with_adjustment_flag": int(row["rows_with_adjustment_flag"] or 0),
            "rows_with_trade_count": int(row["rows_with_trade_count"] or 0),
            "rows_with_bollinger_context": int(row["rows_with_bollinger_context"] or 0),
            "rows_with_temporal_context": int(row["rows_with_temporal_context"] or 0),
            "rows_with_microstructure_context": int(row["rows_with_microstructure_context"] or 0),
            "rows_with_technical_indicators": int(row["rows_with_technical_indicators"] or 0),
            "rows_with_forward_outcome": int(row["rows_with_forward_outcome"] or 0),
            "rows_with_order_flow": int(row["rows_with_order_flow"] or 0),
            "rows_with_fractional_memory": int(row["rows_with_fractional_memory"] or 0),
            "labels": [dict(label) for label in labels],
            "opportunities": [dict(opportunity) for opportunity in opportunities],
            "triple_barriers": [dict(item) for item in triple_barriers],
            "trend_scans": [dict(item) for item in trend_scans],
            "cvd_divergences": [dict(item) for item in cvd_divergences],
        }

    def latest_for_symbol(
        self,
        symbol: str,
        *,
        timeframe: str = "1Min",
        feature_version: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the latest persisted bar-pattern feature row for a symbol."""
        self.init_table()
        params: list[Any] = [symbol.upper(), timeframe]
        extra = ""
        if feature_version:
            extra = " AND feature_version = ?"
            params.append(feature_version)
        with get_connection(self.db_path) as con:
            row = con.execute(
                f"""
                SELECT *
                FROM bar_pattern_features
                WHERE symbol = ?
                  AND timeframe = ?
                  {extra}
                ORDER BY bar_timestamp DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        try:
            payload["feature_json"] = json.loads(payload.get("feature_json") or "{}")
        except Exception:
            payload["feature_json"] = {}
        return payload

    def live_capture_summary(
        self,
        *,
        target_date: str,
        timeframe: str = "1m",
        limit: int = 12,
    ) -> dict[str, Any]:
        """Summarize target-date live bar-pattern capture without changing authority."""
        try:
            start = date.fromisoformat(target_date)
            end_text = (start + timedelta(days=1)).isoformat()
        except Exception:
            end_text = target_date
        with get_connection(self.db_path) as con:
            if not self._table_exists(con):
                return {"table_exists": False, "target_date": target_date}
            columns = self._table_columns(con)

            def select_col(name: str, alias: str | None = None) -> str:
                target = alias or name
                if name in columns:
                    return f"{name} AS {target}"
                return f"NULL AS {target}"

            where = "bar_timestamp >= ? AND bar_timestamp < ? AND timeframe = ?"
            params = [target_date, end_text, timeframe]
            total = con.execute(
                f"""
                SELECT
                    COUNT(*) AS rows,
                    COUNT(DISTINCT symbol) AS symbols,
                    MIN(bar_timestamp) AS first_bar_timestamp,
                    MAX(bar_timestamp) AS latest_bar_timestamp,
                    MAX({("created_at" if "created_at" in columns else "bar_timestamp")}) AS latest_created_at
                FROM bar_pattern_features
                WHERE {where}
                """,
                params,
            ).fetchone()
            sources = []
            if "bar_source" in columns:
                sources = [
                    dict(row)
                    for row in con.execute(
                        f"""
                        SELECT COALESCE(bar_source, 'unknown') AS source, COUNT(*) AS rows
                        FROM bar_pattern_features
                        WHERE {where}
                        GROUP BY COALESCE(bar_source, 'unknown')
                        ORDER BY rows DESC, source
                        """,
                        params,
                    ).fetchall()
                ]
            versions = [
                dict(row)
                for row in con.execute(
                    f"""
                    SELECT COALESCE(feature_version, 'unknown') AS feature_version, COUNT(*) AS rows
                    FROM bar_pattern_features
                    WHERE {where}
                    GROUP BY COALESCE(feature_version, 'unknown')
                    ORDER BY rows DESC, feature_version
                    """,
                    params,
                ).fetchall()
            ]
            latest_rows = [
                dict(row)
                for row in con.execute(
                    f"""
                    WITH ranked AS (
                        SELECT
                            symbol,
                            bar_timestamp,
                            timeframe,
                            {select_col("bar_source", "bar_source")},
                            {select_col("bar_feed", "bar_feed")},
                            feature_version,
                            runtime_effect,
                            {select_col("created_at", "created_at")},
                            {select_col("close", "close")},
                            {select_col("volume", "volume")},
                            {select_col("vwap", "vwap")},
                            {select_col("vpin_toxicity_20", "vpin_toxicity_20")},
                            {select_col("cumulative_volume_delta", "cumulative_volume_delta")},
                            {select_col("trend_scan_label", "trend_scan_label")},
                            {select_col("triple_barrier_label", "triple_barrier_label")},
                            ROW_NUMBER() OVER (
                                PARTITION BY symbol
                                ORDER BY bar_timestamp DESC, id DESC
                            ) AS rn
                        FROM bar_pattern_features
                        WHERE {where}
                    )
                    SELECT *
                    FROM ranked
                    WHERE rn = 1
                    ORDER BY bar_timestamp DESC, symbol
                    LIMIT ?
                    """,
                    [*params, max(1, int(limit or 1))],
                ).fetchall()
            ]
        return {
            "table_exists": True,
            "target_date": target_date,
            "timeframe": timeframe,
            "rows": int(total["rows"] or 0),
            "symbols": int(total["symbols"] or 0),
            "first_bar_timestamp": total["first_bar_timestamp"],
            "latest_bar_timestamp": total["latest_bar_timestamp"],
            "latest_created_at": total["latest_created_at"],
            "sources": sources,
            "feature_versions": versions,
            "latest_rows": latest_rows,
        }

    def volume_clock_source_rows(
        self,
        *,
        target_date: str,
        symbol: str,
        timeframe: str = "1m",
        feature_version: str | None = None,
        limit: int = 20000,
    ) -> list[dict[str, Any]]:
        """Return target-date OHLCV rows for volume-clock VPIN research."""
        try:
            start = date.fromisoformat(target_date)
            end_text = (start + timedelta(days=1)).isoformat()
        except Exception:
            end_text = target_date
        with get_connection(self.db_path) as con:
            if not self._table_exists(con):
                return []
            columns = self._table_columns(con)
            optional = {
                name: name if name in columns else "NULL"
                for name in ("open", "high", "low", "close", "volume", "vwap")
            }
            version_sql = ""
            params: list[Any] = [symbol.upper(), target_date, end_text, timeframe]
            if feature_version:
                version_sql = " AND feature_version = ?"
                params.append(feature_version)
            params.append(max(1, int(limit or 1)))
            rows = con.execute(
                f"""
                SELECT
                    symbol,
                    bar_timestamp,
                    timeframe,
                    {optional["open"]} AS open,
                    {optional["high"]} AS high,
                    {optional["low"]} AS low,
                    {optional["close"]} AS close,
                    {optional["volume"]} AS volume,
                    {optional["vwap"]} AS vwap,
                    feature_version,
                    runtime_effect
                FROM bar_pattern_features
                WHERE symbol = ?
                  AND bar_timestamp >= ?
                  AND bar_timestamp < ?
                  AND timeframe = ?
                  {version_sql}
                ORDER BY bar_timestamp ASC, id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]
