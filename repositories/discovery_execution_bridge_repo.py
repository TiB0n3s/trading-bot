"""Persistence helpers for the paper discovery execution bridge."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection

PENDING = "PENDING"
ROUTING = "ROUTING"
ROUTED = "ROUTED"
FAILED = "FAILED"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class DiscoveryExecutionBridgeRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def claim_candidates(
        self,
        *,
        min_score: float,
        max_candidates: int,
        target_date: str | None,
    ) -> list[dict[str, Any]]:
        timestamp_filter = ""
        params: list[Any] = [min_score, max_candidates]
        if target_date:
            timestamp_filter = "AND substr(candidate_timestamp, 1, 10) = ?"
            params.insert(1, target_date)

        with get_connection(self.db_path) as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute(
                f"""
                SELECT id, candidate_timestamp, symbol, score, candidate_json
                FROM auto_buy_decision_snapshots
                WHERE COALESCE(execution_status, ?) = ?
                  AND decision = 'strong_buy_candidate'
                  AND COALESCE(live_buy_enabled, 0) = 1
                  AND COALESCE(order_submitted, 0) = 0
                  AND score >= ?
                  {timestamp_filter}
                ORDER BY score DESC, id ASC
                LIMIT ?
                """,
                [PENDING, PENDING, *params],
            ).fetchall()
            row_ids = [int(row["id"]) for row in rows]
            if row_ids:
                placeholders = ",".join("?" for _ in row_ids)
                con.execute(
                    f"""
                    UPDATE auto_buy_decision_snapshots
                    SET execution_status = ?,
                        execution_attempted_at = ?,
                        execution_error = NULL
                    WHERE id IN ({placeholders})
                    """,
                    [ROUTING, _now_iso(), *row_ids],
                )
            con.commit()
        return [dict(row) for row in rows]

    def mark_routed(
        self,
        *,
        candidate_id: int,
        symbol: str,
        order_id: str | None,
        order: dict[str, Any],
    ) -> None:
        completed_at = _now_iso()
        order_json = json.dumps(order, sort_keys=True, default=str)
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT candidate_timestamp
                FROM auto_buy_decision_snapshots
                WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
            candidate_timestamp = row["candidate_timestamp"] if row else None
            con.execute(
                """
                UPDATE auto_buy_decision_snapshots
                SET execution_status = ?,
                    routed_order_id = ?,
                    order_submitted = 1,
                    order_id = ?,
                    order_status = ?,
                    order_json = ?,
                    execution_completed_at = ?,
                    execution_error = NULL
                WHERE id = ?
                """,
                (
                    ROUTED,
                    order_id,
                    order_id,
                    str(order.get("status") or "submitted"),
                    order_json,
                    completed_at,
                    candidate_id,
                ),
            )
            if candidate_timestamp:
                con.execute(
                    """
                    UPDATE auto_buy_candidates
                    SET order_submitted = 1,
                        order_id = ?
                    WHERE symbol = ?
                      AND timestamp = ?
                    """,
                    (order_id, symbol, candidate_timestamp),
                )

    def mark_failed(self, *, candidate_id: int, reason: str) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                UPDATE auto_buy_decision_snapshots
                SET execution_status = ?,
                    execution_completed_at = ?,
                    execution_error = ?,
                    live_block_reason = COALESCE(live_block_reason, ?)
                WHERE id = ?
                """,
                (FAILED, _now_iso(), reason, reason, candidate_id),
            )
