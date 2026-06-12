from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, ensure_rejected_signal_outcomes_table, get_connection


class RejectedSignalOutcomeRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def ensure_table(self) -> None:
        ensure_rejected_signal_outcomes_table(self.db_path)

    def _decision_snapshot_for_trade(self, con, trade_id: int) -> dict[str, Any]:
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'decision_snapshots'"
        ).fetchone()
        if not table:
            return {}

        columns = {
            row["name"] for row in con.execute("PRAGMA table_info(decision_snapshots)").fetchall()
        }
        required = {
            "id",
            "trade_id",
            "canonical_intelligence_version",
            "canonical_intelligence_hash",
            "canonical_intelligence_json",
        }
        if not required <= columns:
            return {}

        row = con.execute(
            """
            SELECT
                id,
                canonical_intelligence_version,
                canonical_intelligence_hash,
                canonical_intelligence_json
            FROM decision_snapshots
            WHERE trade_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (trade_id,),
        ).fetchone()
        return dict(row) if row else {}

    def rejected_rows(
        self, clauses: list[str], params: list[Any], limit: int | None = None
    ) -> list[Any]:
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
                WHERE {" AND ".join(clauses)}
                ORDER BY timestamp ASC, id ASC
                {limit_sql}
                """,
                query_params,
            ).fetchall()

    def rejected_decision_snapshot_rows(
        self,
        *,
        target_date: str,
        limit: int | None = None,
        symbol: str | None = None,
    ) -> list[Any]:
        """Decision snapshots rejected before order routing.

        The legacy builder labels rejected rows from ``trades``. Paper-only
        discovery/decision paths can reject before a trade row exists, so those
        snapshots need their own counterfactual outcome path.
        """
        self.ensure_table()
        query_params: list[Any] = [target_date]
        clauses = [
            "substr(ds.decision_time, 1, 10) = ?",
            "COALESCE(ds.approved, 0) = 0",
            "ds.trade_id IS NULL",
            "ds.symbol IS NOT NULL",
            "ds.action IS NOT NULL",
            "ds.signal_price IS NOT NULL",
            "LOWER(ds.action) IN ('buy', 'sell')",
            "rso.id IS NULL",
        ]
        if symbol:
            clauses.append("UPPER(ds.symbol) = ?")
            query_params.append(symbol.upper())
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            query_params.append(int(limit))

        with get_connection(self.db_path) as con:
            table = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'decision_snapshots'"
            ).fetchone()
            if not table:
                return []
            return con.execute(
                f"""
                SELECT
                    ds.id,
                    ds.decision_time AS timestamp,
                    ds.symbol,
                    ds.action,
                    ds.signal_price,
                    ds.rejection_reason,
                    ds.canonical_intelligence_version,
                    ds.canonical_intelligence_hash,
                    ds.canonical_intelligence_json
                FROM decision_snapshots ds
                LEFT JOIN rejected_signal_outcomes rso
                  ON rso.decision_snapshot_id = ds.id
                 AND rso.trade_id IS NULL
                WHERE {" AND ".join(clauses)}
                ORDER BY ds.decision_time ASC, ds.id ASC
                {limit_sql}
                """,
                query_params,
            ).fetchall()

    def upsert_outcome(self, row: Any, outcome: dict[str, Any], source: str) -> None:
        self.ensure_table()
        with get_connection(self.db_path) as con:
            snapshot = self._decision_snapshot_for_trade(con, int(row["id"]))
            con.execute(
                """
                INSERT INTO rejected_signal_outcomes (
                    trade_id, timestamp, symbol, action, signal_price, rejection_reason,
                    return_5m, return_15m, return_30m, return_60m, return_eod,
                    max_favorable_60m, max_adverse_60m,
                    label_status, partial_reason, source,
                    decision_snapshot_id, canonical_intelligence_version,
                    canonical_intelligence_hash, canonical_intelligence_json,
                    generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
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
                    decision_snapshot_id = excluded.decision_snapshot_id,
                    canonical_intelligence_version = excluded.canonical_intelligence_version,
                    canonical_intelligence_hash = excluded.canonical_intelligence_hash,
                    canonical_intelligence_json = excluded.canonical_intelligence_json,
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
                    snapshot.get("id"),
                    snapshot.get("canonical_intelligence_version"),
                    snapshot.get("canonical_intelligence_hash"),
                    snapshot.get("canonical_intelligence_json"),
                ),
            )

    def upsert_decision_snapshot_outcome(
        self,
        row: Any,
        outcome: dict[str, Any],
        source: str,
    ) -> None:
        """Upsert a counterfactual outcome for a snapshot-only rejection."""
        self.ensure_table()
        with get_connection(self.db_path) as con:
            con.execute(
                """
                DELETE FROM rejected_signal_outcomes
                WHERE decision_snapshot_id = ?
                  AND trade_id IS NULL
                """,
                (int(row["id"]),),
            )
            con.execute(
                """
                INSERT INTO rejected_signal_outcomes (
                    trade_id, timestamp, symbol, action, signal_price, rejection_reason,
                    return_5m, return_15m, return_30m, return_60m, return_eod,
                    max_favorable_60m, max_adverse_60m,
                    label_status, partial_reason, source,
                    decision_snapshot_id, canonical_intelligence_version,
                    canonical_intelligence_hash, canonical_intelligence_json,
                    generated_at
                ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
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
                    int(row["id"]),
                    row["canonical_intelligence_version"],
                    row["canonical_intelligence_hash"],
                    row["canonical_intelligence_json"],
                ),
            )
