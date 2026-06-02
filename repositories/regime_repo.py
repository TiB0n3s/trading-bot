"""Repository helpers for regime status and training inputs."""

from __future__ import annotations

import sqlite3
from typing import Any

from db import DB_PATH


SPY_CLOSES_QUERY = """
    SELECT last_price
    FROM feature_snapshots
    WHERE symbol = 'SPY'
      AND last_price IS NOT NULL
    ORDER BY timestamp DESC
    LIMIT ?
"""


def fetch_spy_closes(limit: int, *, db_path: Any = DB_PATH) -> list[float]:
    """Return recent SPY closes in chronological order."""
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(SPY_CLOSES_QUERY, (int(limit),)).fetchall()
        return [float(row["last_price"]) for row in reversed(rows)]
    except Exception:
        return []
