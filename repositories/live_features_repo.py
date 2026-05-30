"""Repository boundary for live feature snapshots."""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection


class LiveFeaturesRepository:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def recent_actions(self, symbol: str, limit: int = 10) -> list[str]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT action
                FROM trades
                WHERE symbol = ?
                  AND action IS NOT NULL
                  AND (
                        approved = 1
                     OR rejection_reason LIKE 'confidence_gate:%'
                     OR rejection_reason LIKE 'trend_gate:%'
                     OR rejection_reason LIKE 'trend_confirmation:%'
                  )
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()

        return [row["action"] for row in rows]

    def insert_snapshot(self, snapshot: dict[str, Any]) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                INSERT INTO feature_snapshots (
                    timestamp,
                    symbol,
                    last_price,
                    ret_1m,
                    ret_5m,
                    ret_15m,
                    range_pos_15m,
                    distance_from_5m_high,
                    distance_from_5m_low,
                    distance_from_vwap,
                    volume_ratio_5m,
                    benchmark_symbol,
                    benchmark_ret_5m,
                    relative_strength_5m,
                    spread_pct,
                    market_session,
                    macro_regime,
                    market_bias,
                    trend_direction,
                    trend_strength,
                    feature_available_at,
                    feature_generated_at,
                    feature_age_seconds,
                    source,
                    is_stale,
                    staleness_reason,
                    bar_timeframe,
                    bar_count,
                    setup_label,
                    setup_recommendation,
                    setup_score,
                    setup_confidence,
                    setup_key,
                    momentum_acceleration_pct,
                    volume_surge_ratio,
                    extension_from_recent_base_pct,
                    prior_session_return_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.get("timestamp"),
                    snapshot.get("symbol"),
                    snapshot.get("last_price"),
                    snapshot.get("ret_1m"),
                    snapshot.get("ret_5m"),
                    snapshot.get("ret_15m"),
                    snapshot.get("range_pos_15m"),
                    snapshot.get("distance_from_5m_high"),
                    snapshot.get("distance_from_5m_low"),
                    snapshot.get("distance_from_vwap"),
                    snapshot.get("volume_ratio_5m"),
                    snapshot.get("benchmark_symbol"),
                    snapshot.get("benchmark_ret_5m"),
                    snapshot.get("relative_strength_5m"),
                    snapshot.get("spread_pct"),
                    snapshot.get("market_session"),
                    snapshot.get("macro_regime"),
                    snapshot.get("market_bias"),
                    snapshot.get("trend_direction"),
                    snapshot.get("trend_strength"),
                    snapshot.get("feature_available_at"),
                    snapshot.get("feature_generated_at"),
                    snapshot.get("feature_age_seconds"),
                    snapshot.get("source"),
                    snapshot.get("is_stale"),
                    snapshot.get("staleness_reason"),
                    snapshot.get("bar_timeframe"),
                    snapshot.get("bar_count"),
                    snapshot.get("setup_label"),
                    snapshot.get("setup_recommendation"),
                    snapshot.get("setup_score"),
                    snapshot.get("setup_confidence"),
                    snapshot.get("setup_key"),
                    snapshot.get("momentum_acceleration_pct"),
                    snapshot.get("volume_surge_ratio"),
                    snapshot.get("extension_from_recent_base_pct"),
                    snapshot.get("prior_session_return_pct"),
                ),
            )
