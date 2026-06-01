"""Repository reads for symbol momentum timing intelligence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class SymbolMomentumTimingRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def load_feature_label_rows(
        self,
        target_date: str,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [target_date]
        extra = ""

        if symbol:
            extra += " AND fs.symbol = ?"
            params.append(symbol.upper())

        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            params.append(limit)

        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT
                    fs.id AS snapshot_id,
                    fs.timestamp,
                    fs.symbol,
                    fs.last_price,
                    fs.ret_1m,
                    fs.ret_5m,
                    fs.ret_15m,
                    fs.range_pos_15m,
                    fs.distance_from_5m_high,
                    fs.distance_from_5m_low,
                    fs.distance_from_vwap,
                    fs.volume_ratio_5m,
                    fs.benchmark_symbol,
                    fs.benchmark_ret_5m,
                    fs.relative_strength_5m,
                    fs.spread_pct,
                    fs.market_session,
                    fs.macro_regime,
                    fs.market_bias,
                    fs.trend_direction,
                    fs.trend_strength,
                    fs.bar_timeframe,
                    fs.bar_count,
                    fs.setup_label,
                    fs.setup_recommendation,
                    fs.setup_score,
                    fs.setup_confidence,
                    fs.momentum_acceleration_pct,
                    fs.volume_surge_ratio,
                    fs.extension_from_recent_base_pct,
                    fs.prior_session_return_pct,
                    ls.ret_fwd_5m,
                    ls.ret_fwd_15m,
                    ls.ret_fwd_30m,
                    ls.max_up_15m,
                    ls.max_down_15m,
                    ls.outcome_label,
                    CASE
                        WHEN ls.snapshot_id IS NULL
                            THEN 'unlabeled'
                        WHEN ls.ret_fwd_5m IS NULL
                         AND ls.ret_fwd_15m IS NULL
                         AND ls.ret_fwd_30m IS NULL
                            THEN 'incomplete'
                        WHEN ls.ret_fwd_30m IS NULL
                            THEN 'partial_near_close'
                        ELSE 'complete'
                    END AS label_horizon_status
                FROM feature_snapshots fs
                LEFT JOIN labeled_setups ls
                  ON ls.snapshot_id = fs.id
                WHERE substr(fs.timestamp, 1, 10) = ?
                  {extra}
                ORDER BY fs.symbol, fs.timestamp, fs.id
                {limit_sql}
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]
