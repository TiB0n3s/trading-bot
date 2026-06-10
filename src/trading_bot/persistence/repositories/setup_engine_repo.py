"""Repository boundary for setup-engine feature snapshot reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection

FEATURE_SNAPSHOT_COLUMNS = """
    id,
    timestamp,
    symbol,
    market_session,
    market_bias,
    trend_direction,
    trend_strength,
    relative_strength_5m,
    distance_from_vwap,
    ret_5m,
    ret_15m,
    bar_timeframe,
    bar_count,
    momentum_acceleration_pct,
    volume_surge_ratio,
    extension_from_recent_base_pct,
    prior_session_return_pct
"""


class SetupEngineRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def load_snapshot_by_id(self, snapshot_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as con:
            row = con.execute(
                f"""
                SELECT {FEATURE_SNAPSHOT_COLUMNS}
                FROM feature_snapshots
                WHERE id = ?
                """,
                (snapshot_id,),
            ).fetchone()

        return dict(row) if row else None

    def load_latest_snapshot_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as con:
            row = con.execute(
                f"""
                SELECT {FEATURE_SNAPSHOT_COLUMNS}
                FROM feature_snapshots
                WHERE symbol = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (symbol.upper(),),
            ).fetchone()

        return dict(row) if row else None
