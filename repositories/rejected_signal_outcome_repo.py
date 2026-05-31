from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, ensure_rejected_signal_outcomes_table, get_connection


class RejectedSignalOutcomeRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def ensure_table(self) -> None:
        ensure_rejected_signal_outcomes_table(self.db_path)

    def rejected_rows(self, clauses: list[str], params: list[Any], limit: int | None = None) -> list[Any]:
        query_params = list(params)
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            query_params.append(int(limit))

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT id, timestamp, symbol, action, signal_price, rejection_reason
                FROM trades
                WHERE {' AND '.join(clauses)}
                ORDER BY timestamp ASC, id ASC
                {limit_sql}
                """,
                query_params,
            ).fetchall()

    def upsert_outcome(self, row: Any, outcome: dict[str, Any], source: str) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                INSERT INTO rejected_signal_outcomes (
                    trade_id, timestamp, symbol, action, signal_price, rejection_reason,
                    return_5m, return_15m, return_30m, return_60m, return_eod,
                    max_favorable_60m, max_adverse_60m,
                    label_status, partial_reason, source, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(trade_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    symbol = excluded.symbol,
                    action = excluded.action,
                    signal_price = excluded.signal_price,
                    rejection_reason = excluded.rejection_reason,
                    return_5m = excluded.return_5m,
                    return_15m = excluded.return_15m,
                    return_30m = excluded.return_30m,
                    return_60m = excluded.return_60m,
                    return_eod = excluded.return_eod,
                    max_favorable_60m = excluded.max_favorable_60m,
                    max_adverse_60m = excluded.max_adverse_60m,
                    label_status = excluded.label_status,
                    partial_reason = excluded.partial_reason,
                    source = excluded.source,
                    generated_at = excluded.generated_at
                """,
                (
                    row["id"],
                    row["timestamp"],
                    row["symbol"],
                    row["action"],
                    row["signal_price"],
                    row["rejection_reason"],
                    outcome.get("return_5m"),
                    outcome.get("return_15m"),
                    outcome.get("return_30m"),
                    outcome.get("return_60m"),
                    outcome.get("return_eod"),
                    outcome.get("max_favorable_60m"),
                    outcome.get("max_adverse_60m"),
                    outcome.get("label_status") or "pending",
                    outcome.get("partial_reason"),
                    source,
                ),
            )
