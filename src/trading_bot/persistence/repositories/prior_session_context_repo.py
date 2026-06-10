"""Repository boundary for prior-session context reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class PriorSessionContextRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def latest_strong_day_participation(self, symbol: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as con:
            table = con.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'strong_day_participation'
                """
            ).fetchone()
            if not table:
                return None

            row = con.execute(
                """
                SELECT market_date,
                       session_return_pct,
                       primary_status,
                       buy_signal_count,
                       approved_buy_count,
                       rejected_buy_count,
                       sell_signal_count,
                       auto_buy_candidate_count,
                       auto_buy_strong_count
                FROM strong_day_participation
                WHERE symbol = ?
                ORDER BY market_date DESC, id DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()

        return dict(row) if row else None
