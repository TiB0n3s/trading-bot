"""Repository reads for filter effectiveness reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


@dataclass(frozen=True)
class TradeFilter:
    target_like: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    symbol: str | None = None


class FilterReportRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def db_exists(self) -> bool:
        return self.db_path.exists()

    def _where(self, trade_filter: TradeFilter) -> tuple[str, list[Any]]:
        clauses = []
        params: list[Any] = []

        if trade_filter.target_like:
            clauses.append("timestamp LIKE ?")
            params.append(trade_filter.target_like)

        if trade_filter.start_date and trade_filter.end_date:
            clauses.append("timestamp >= ? AND timestamp < ?")
            params.extend([trade_filter.start_date, trade_filter.end_date])

        if trade_filter.symbol:
            clauses.append("symbol = ?")
            params.append(trade_filter.symbol.upper())

        where = " AND ".join(clauses)
        return (f" AND {where}" if where else ""), params

    def rejected_rows(self, trade_filter: TradeFilter) -> list[dict[str, Any]]:
        extra, params = self._where(trade_filter)
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT id, timestamp, symbol, action, approved, rejection_reason,
                       market_bias, risk_level, entry_quality,
                       trend_direction, trend_strength,
                       momentum_direction, momentum_pct,
                       macro_regime, risk_multiplier,
                       correlation_cluster, cluster_exposure_pct
                FROM trades
                WHERE approved = 0
                  AND rejection_reason IS NOT NULL
                  {extra}
                ORDER BY id DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def total_signals(self, trade_filter: TradeFilter) -> int:
        extra, params = self._where(trade_filter)
        with get_connection(self.db_path) as con:
            row = con.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM trades
                WHERE 1=1
                  {extra}
                """,
                params,
            ).fetchone()
        return int(row["n"] or 0)

    def approved_signals(self, trade_filter: TradeFilter) -> int:
        extra, params = self._where(trade_filter)
        with get_connection(self.db_path) as con:
            row = con.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM trades
                WHERE approved = 1
                  {extra}
                """,
                params,
            ).fetchone()
        return int(row["n"] or 0)
