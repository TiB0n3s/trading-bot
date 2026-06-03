"""Persistence for observe-only EFI/PVT bar-pattern learning rows."""

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
                    timeframe TEXT NOT NULL,
                    close REAL,
                    volume REAL,
                    efi REAL,
                    efi_ema_13 REAL,
                    efi_slope_3 REAL,
                    efi_zscore_20 REAL,
                    pvt REAL,
                    pvt_slope_5 REAL,
                    pvt_new_high_30 INTEGER,
                    price_return_5 REAL,
                    price_vs_sma_20_pct REAL,
                    breakout_20 INTEGER,
                    pattern_label TEXT,
                    pattern_score REAL,
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

    def upsert_many(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.init_table()
        with get_connection(self.db_path) as con:
            con.executemany(
                """
                INSERT INTO bar_pattern_features (
                    symbol, bar_timestamp, timeframe, close, volume,
                    efi, efi_ema_13, efi_slope_3, efi_zscore_20,
                    pvt, pvt_slope_5, pvt_new_high_30,
                    price_return_5, price_vs_sma_20_pct, breakout_20,
                    pattern_label, pattern_score,
                    forward_return_pct, forward_mfe_pct, forward_mae_pct,
                    horizon_bars, feature_version, runtime_effect, feature_json
                ) VALUES (
                    :symbol, :bar_timestamp, :timeframe, :close, :volume,
                    :efi, :efi_ema_13, :efi_slope_3, :efi_zscore_20,
                    :pvt, :pvt_slope_5, :pvt_new_high_30,
                    :price_return_5, :price_vs_sma_20_pct, :breakout_20,
                    :pattern_label, :pattern_score,
                    :forward_return_pct, :forward_mfe_pct, :forward_mae_pct,
                    :horizon_bars, :feature_version, :runtime_effect, :feature_json
                )
                ON CONFLICT(symbol, bar_timestamp, timeframe, feature_version)
                DO UPDATE SET
                    close = excluded.close,
                    volume = excluded.volume,
                    efi = excluded.efi,
                    efi_ema_13 = excluded.efi_ema_13,
                    efi_slope_3 = excluded.efi_slope_3,
                    efi_zscore_20 = excluded.efi_zscore_20,
                    pvt = excluded.pvt,
                    pvt_slope_5 = excluded.pvt_slope_5,
                    pvt_new_high_30 = excluded.pvt_new_high_30,
                    price_return_5 = excluded.price_return_5,
                    price_vs_sma_20_pct = excluded.price_vs_sma_20_pct,
                    breakout_20 = excluded.breakout_20,
                    pattern_label = excluded.pattern_label,
                    pattern_score = excluded.pattern_score,
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
                    SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END)
                        AS rows_with_forward_outcome
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
        return {
            "rows": int(row["rows"] or 0),
            "symbols": int(row["symbols"] or 0),
            "rows_with_forward_outcome": int(row["rows_with_forward_outcome"] or 0),
            "labels": [dict(label) for label in labels],
        }
