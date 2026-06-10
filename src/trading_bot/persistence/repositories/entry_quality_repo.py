"""Repository reads for entry-quality reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection

ENTRY_QUALITY_SELECT = """
    SELECT ds.symbol,
           ds.decision_time,
           ds.momentum_state,
           ds.volume_state,
           ds.extension_from_recent_base_pct,
           ds.rolling_special_labels,
           ds.prior_session_return_pct,
           ds.prior_session_participated,
           ds.tape_label_at_signal,
           ds.tape_bar_age_seconds,
           ds.setup_label,
           ds.setup_score,
           ds.setup_rationale,
           mt.realized_pnl_pct,
           mt.won,
           mt.exit_reason,
           mt.holding_minutes
    FROM decision_snapshots ds
    JOIN trades t ON t.id = ds.trade_id
    JOIN matched_trades mt
      ON mt.symbol = t.symbol
     AND mt.entry_timestamp = t.timestamp
"""


class EntryQualityRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def rows_for_date(self, target_date: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                {ENTRY_QUALITY_SELECT}
                WHERE substr(ds.decision_time, 1, 10) = ?
                  AND lower(ds.action) = 'buy'
                  AND ds.approved = 1
                  AND mt.realized_pnl_pct IS NOT NULL
                ORDER BY ds.decision_time ASC, ds.symbol ASC
                """,
                (target_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def rows_all(self) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                {ENTRY_QUALITY_SELECT}
                WHERE lower(ds.action) = 'buy'
                  AND ds.approved = 1
                  AND mt.realized_pnl_pct IS NOT NULL
                ORDER BY ds.decision_time ASC, ds.symbol ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]
