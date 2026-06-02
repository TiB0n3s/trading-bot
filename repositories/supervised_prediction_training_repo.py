"""Repository reads for supervised prediction training datasets."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH


def fetch_training_rows(
    *,
    db_path: Path | str = DB_PATH,
    symbol: str | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    symbol_sql = ""
    params: list[Any] = []
    if symbol:
        symbol_sql = "AND fs.symbol = ?"
        params.append(symbol.upper())
    params.append(limit)
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
                ls.ret_fwd_5m,
                ls.ret_fwd_15m,
                ls.ret_fwd_30m
            FROM feature_snapshots fs
            JOIN labeled_setups ls ON ls.snapshot_id = fs.id
            WHERE ls.ret_fwd_15m IS NOT NULL
              {symbol_sql}
            ORDER BY fs.timestamp DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]
