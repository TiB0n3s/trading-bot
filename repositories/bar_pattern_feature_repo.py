"""Persistence for observe-only advanced per-bar learning rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class BarPatternFeatureRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

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
                    macd REAL,
                    macd_signal REAL,
                    rsi_14 REAL,
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
            self._ensure_column(con, "macd", "REAL")
            self._ensure_column(con, "macd_signal", "REAL")
            self._ensure_column(con, "rsi_14", "REAL")
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
                    session_phase, bid_price, ask_price, bid_ask_spread_pct,
                    slippage_estimate_pct, execution_cost_estimate_pct,
                    liquidity_zone_label, liquidity_sweep_risk, ema_12,
                    ema_26, macd, macd_signal, rsi_14,
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
                    :day_of_week, :minute_of_day, :session_phase,
                    :bid_price, :ask_price, :bid_ask_spread_pct,
                    :slippage_estimate_pct, :execution_cost_estimate_pct,
                    :liquidity_zone_label, :liquidity_sweep_risk, :ema_12,
                    :ema_26, :macd, :macd_signal, :rsi_14,
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
                    macd = excluded.macd,
                    macd_signal = excluded.macd_signal,
                    rsi_14 = excluded.rsi_14,
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
        params: list[Any] = [target_date]
        extra = ""
        if symbol:
            extra = " AND symbol = ?"
            params.append(symbol.upper())
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
                    SUM(CASE WHEN ema_12 IS NOT NULL AND ema_26 IS NOT NULL AND macd IS NOT NULL AND rsi_14 IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_technical_indicators,
                    SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_forward_outcome,
                    SUM(CASE WHEN cvd_price_corr_20 IS NOT NULL OR vpin_toxicity_20 IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_order_flow,
                    SUM(CASE WHEN fractional_diff_zscore_20 IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_fractional_memory
                FROM bar_pattern_features
                WHERE substr(bar_timestamp, 1, 10) = ?
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
                WHERE substr(bar_timestamp, 1, 10) = ?
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
                WHERE substr(bar_timestamp, 1, 10) = ?
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
                WHERE substr(bar_timestamp, 1, 10) = ?
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
                WHERE substr(bar_timestamp, 1, 10) = ?
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
                WHERE substr(bar_timestamp, 1, 10) = ?
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
