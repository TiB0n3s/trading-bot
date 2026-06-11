"""Repository reads for supervised prediction training datasets."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH
from services.bar_pattern_feature_service import BAR_PATTERN_FEATURE_VERSION
from services.spacex_value_chain_service import build_spacex_value_chain_feature
from services.value_chain_eco_cluster_service import (
    build_value_chain_eco_cluster_feature,
    build_value_chain_eco_cluster_graph,
)

SNAPSHOT_JOIN_FEATURE_VERSION_ALIASES = (
    BAR_PATTERN_FEATURE_VERSION,
    "v4",
    "efi_pvt_orderflow_math_bar_pattern_v3",
)


def _attach_reference_features(row: dict[str, Any], *, eco_graph=None) -> dict[str, Any]:
    feature = build_spacex_value_chain_feature(symbol=str(row.get("symbol") or ""))
    shock = feature.get("lead_lag_shock") or {}
    eco_feature = build_value_chain_eco_cluster_feature(
        symbol=str(row.get("symbol") or ""),
        graph=eco_graph,
    )
    enriched = dict(row)
    enriched["spacex_value_chain_in_scope"] = bool(feature.get("in_value_chain"))
    enriched["spacex_value_chain_authority_tier"] = feature.get("authority_tier")
    enriched["spacex_value_chain_relationship_type"] = feature.get("relationship_type")
    enriched["spacex_value_chain_relationship_weight"] = feature.get("relationship_weight")
    enriched["spacex_value_chain_information_shock_score"] = shock.get("information_shock_score")
    enriched["spacex_value_chain_liquidity_siphon_ratio"] = feature.get("liquidity_siphon_ratio")
    enriched["value_chain_eco_cluster_in_scope"] = bool(eco_feature.get("in_eco_cluster"))
    enriched["value_chain_eco_cluster_authority_tier"] = eco_feature.get("authority_tier")
    enriched["value_chain_eco_cluster_graph_degree"] = eco_feature.get("graph_degree")
    enriched["value_chain_eco_cluster_max_relationship_weight"] = eco_feature.get(
        "max_relationship_weight"
    )
    enriched["value_chain_eco_cluster_avg_relationship_weight"] = eco_feature.get(
        "avg_relationship_weight"
    )
    enriched["value_chain_eco_cluster_linked_context_count"] = eco_feature.get(
        "linked_context_count"
    )
    return enriched


def fetch_training_rows(
    *,
    db_path: Path | str = DB_PATH,
    symbol: str | None = None,
    limit: int = 5000,
    prediction_time_cutoff: str | None = None,
) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    symbol_sql = ""
    params: list[Any] = []
    limit_param = int(limit)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='feature_snapshots'"
        ).fetchone()
        labels = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='labeled_setups'"
        ).fetchone()
        if not exists or not labels:
            return []
        fs_cols = {
            row["name"] for row in con.execute("PRAGMA table_info(feature_snapshots)").fetchall()
        }
        has_bar_patterns = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bar_pattern_features'"
        ).fetchone()
        bp_cols = set()
        if has_bar_patterns:
            bp_cols = {
                row["name"]
                for row in con.execute("PRAGMA table_info(bar_pattern_features)").fetchall()
            }
        bp_version_filter = ""
        if "feature_version" in bp_cols:
            values = ", ".join(f"'{value}'" for value in SNAPSHOT_JOIN_FEATURE_VERSION_ALIASES)
            bp_version_filter = f"AND bp2.feature_version IN ({values})"

        def bp_expr(name: str) -> str:
            return f"bp.{name}" if name in bp_cols else f"NULL AS {name}"

        bar_pattern_join = ""
        if has_bar_patterns:
            bar_pattern_join = f"""
                LEFT JOIN bar_pattern_features bp
                  ON bp.rowid = (
                    SELECT MAX(bp2.rowid)
                    FROM bar_pattern_features bp2
                    WHERE bp2.symbol = fs.symbol
                      AND bp2.timeframe = '1m'
                      AND bp2.bar_timestamp <= strftime('%Y-%m-%dT%H:%M:%S', fs.timestamp) || '+00:00'
                      AND bp2.bar_timestamp >= strftime('%Y-%m-%dT%H:%M:%S', datetime(fs.timestamp, '-90 seconds')) || '+00:00'
                      {bp_version_filter}
                 )
            """
        point_in_time_sql = ""
        if prediction_time_cutoff:
            if "feature_available_at" in fs_cols:
                point_in_time_sql = "AND datetime(fs.feature_available_at) <= datetime(?)"
            else:
                point_in_time_sql = "AND datetime(fs.timestamp) <= datetime(?)"
            params.append(prediction_time_cutoff)
        if symbol:
            symbol_sql = "AND fs.symbol = ?"
            params.append(symbol.upper())
        params.append(limit_param)
        rows = con.execute(
            f"""
            SELECT
                fs.symbol,
                fs.timestamp,
                fs.ret_1m,
                fs.ret_5m,
                fs.ret_15m,
                fs.range_pos_15m,
                fs.distance_from_vwap,
                fs.volume_ratio_5m,
                fs.relative_strength_5m,
                fs.spread_pct,
                fs.setup_score,
                {bp_expr("sma_20")},
                {bp_expr("bollinger_upper_20")},
                {bp_expr("bollinger_lower_20")},
                {bp_expr("bollinger_width_20_pct")},
                {bp_expr("bollinger_percent_b_20")},
                {bp_expr("rolling_volatility_20_pct")},
                {bp_expr("day_of_week")},
                {bp_expr("minute_of_day")},
                {bp_expr("day_of_month")},
                {bp_expr("week_of_month")},
                {bp_expr("month_end_proximity_days")},
                {bp_expr("monday_volatility_flag")},
                {bp_expr("friday_rebalance_flag")},
                {bp_expr("prior_session_return_pct")},
                {bp_expr("prior_5_session_return_pct")},
                {bp_expr("candle_body_pct")},
                {bp_expr("upper_wick_pct")},
                {bp_expr("lower_wick_pct")},
                {bp_expr("upper_lower_wick_ratio")},
                {bp_expr("close_location")},
                {bp_expr("range_atr_ratio")},
                {bp_expr("atr_20_pct")},
                {bp_expr("volume_ratio_20")},
                {bp_expr("pressure_return_3")},
                {bp_expr("pressure_return_8")},
                {bp_expr("volume_weighted_pressure_3")},
                {bp_expr("volume_delta")},
                {bp_expr("institutional_volume_delta")},
                {bp_expr("cumulative_volume_delta")},
                {bp_expr("cvd_price_corr_20")},
                {bp_expr("vpin_toxicity_20")},
                {bp_expr("fractional_diff_close_045")},
                {bp_expr("fractional_diff_zscore_20")},
                {bp_expr("bid_ask_spread_pct")},
                {bp_expr("slippage_estimate_pct")},
                {bp_expr("execution_cost_estimate_pct")},
                {bp_expr("liquidity_sweep_risk")},
                {bp_expr("ema_12")},
                {bp_expr("ema_26")},
                {bp_expr("ema_200")},
                {bp_expr("price_vs_ema_200_pct")},
                {bp_expr("closes_above_ema_200_5")},
                {bp_expr("closes_below_ema_200_5")},
                {bp_expr("macd")},
                {bp_expr("macd_signal")},
                {bp_expr("macd_histogram")},
                {bp_expr("macd_histogram_pct")},
                {bp_expr("macd_bullish_cross")},
                {bp_expr("macd_bearish_cross")},
                {bp_expr("macd_bearish_divergence")},
                {bp_expr("ema200_macd_reversal_score")},
                {bp_expr("rsi_14")},
                {bp_expr("webull_rsi_14")},
                {bp_expr("webull_rsi_bearish_divergence")},
                {bp_expr("trend_scan_label")},
                {bp_expr("trend_scan_tstat")},
                {bp_expr("trend_scan_bars")},
                {bp_expr("trend_scan_return_pct")},
                {bp_expr("pattern_label")},
                {bp_expr("pattern_score")},
                {bp_expr("opportunity_action")},
                {bp_expr("opportunity_quality")},
                {bp_expr("long_opportunity_score")},
                {bp_expr("sell_opportunity_score")},
                {bp_expr("triple_barrier_label")},
                {bp_expr("triple_barrier_reason")},
                {bp_expr("triple_barrier_bars_to_event")},
                {bp_expr("triple_barrier_profit_pct")},
                {bp_expr("triple_barrier_stop_pct")},
                ls.ret_fwd_5m,
                ls.ret_fwd_15m,
                ls.ret_fwd_30m
            FROM feature_snapshots fs
            JOIN labeled_setups ls ON ls.snapshot_id = fs.id
            {bar_pattern_join}
            WHERE ls.ret_fwd_15m IS NOT NULL
              {point_in_time_sql}
              {symbol_sql}
            ORDER BY fs.timestamp DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    eco_graph = build_value_chain_eco_cluster_graph()
    return [_attach_reference_features(dict(row), eco_graph=eco_graph) for row in rows]
