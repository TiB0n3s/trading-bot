"""Repository reads for blocked-signal outcome reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


@dataclass(frozen=True)
class BlockedSignalFilter:
    target_like: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    symbol: str | None = None


class BlockedSignalOutcomeRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def db_exists(self) -> bool:
        return self.db_path.exists()

    def _where(self, signal_filter: BlockedSignalFilter) -> tuple[str, list[Any]]:
        clauses = []
        params: list[Any] = []

        if signal_filter.target_like:
            clauses.append("timestamp LIKE ?")
            params.append(signal_filter.target_like)

        if signal_filter.start_date and signal_filter.end_date:
            clauses.append("timestamp >= ? AND timestamp < ?")
            params.extend([signal_filter.start_date, signal_filter.end_date])

        if signal_filter.symbol:
            clauses.append("symbol = ?")
            params.append(signal_filter.symbol.upper())

        where = " AND ".join(clauses)
        return (f" AND {where}" if where else ""), params

    def blocked_buy_rows(
        self,
        signal_filter: BlockedSignalFilter,
    ) -> list[dict[str, Any]]:
        extra, params = self._where(signal_filter)
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT
                    id,
                    timestamp,
                    symbol,
                    action,
                    signal_price,
                    rejection_reason,
                    market_bias,
                    market_bias_effective,
                    market_bias_override_reason,
                    fundamental_score,
                    risk_level,
                    entry_quality,
                    trend_direction,
                    trend_strength,
                    momentum_direction,
                    momentum_pct,
                    session_trend_label,
                    session_trend_score,
                    session_return_pct,
                    session_momentum_5m_pct,
                    session_momentum_15m_pct,
                    session_momentum_30m_pct,
                    session_distance_from_vwap_pct,
                    session_momentum_reason,
                    prediction_score,
                    prediction_decision,
                    prediction_reason,
                    setup_label,
                    setup_policy_action,
                    setup_policy_reason
                FROM trades
                WHERE approved = 0
                  AND LOWER(action) = 'buy'
                  AND rejection_reason IS NOT NULL
                  {extra}
                ORDER BY id DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]
