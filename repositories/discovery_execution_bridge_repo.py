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
        min_candidate_timestamp: str | None,
        recent_route_cutoff: str | None,
    ) -> list[dict[str, Any]]:
        timestamp_filter = ""
        latest_timestamp_filter = ""
        fresh_filter = ""
        recent_route_filter = ""
        params: list[Any] = [min_score]
        if target_date:
            timestamp_filter = "AND substr(snap.candidate_timestamp, 1, 10) = ?"
            latest_timestamp_filter = "AND substr(latest.candidate_timestamp, 1, 10) = ?"
            params.append(target_date)
            params.append(target_date)
        if min_candidate_timestamp:
            fresh_filter = "AND snap.candidate_timestamp >= ?"
            params.append(min_candidate_timestamp)
        if recent_route_cutoff:
            recent_route_filter = """
                  AND NOT EXISTS (
                      SELECT 1
                      FROM auto_buy_decision_snapshots routed
                      WHERE routed.symbol = snap.symbol
                        AND routed.execution_status = ?
                        AND routed.candidate_timestamp >= ?
                  )
            """
            params.extend([ROUTED, recent_route_cutoff])
        params.append(max_candidates)

        with get_connection(self.db_path) as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute(
                f"""
                SELECT snap.id, snap.candidate_timestamp, snap.symbol, snap.score, snap.candidate_json
                FROM auto_buy_decision_snapshots snap
                WHERE COALESCE(snap.execution_status, ?) = ?
                  AND snap.decision = 'strong_buy_candidate'
                  AND COALESCE(snap.live_buy_enabled, 0) = 1
                  AND COALESCE(snap.order_submitted, 0) = 0
                  AND snap.score >= ?
                  AND snap.id = (
                      SELECT MAX(latest.id)
                      FROM auto_buy_decision_snapshots latest
                      WHERE latest.symbol = snap.symbol
                        {latest_timestamp_filter}
                  )
                  {timestamp_filter}
                  {fresh_filter}
                  {recent_route_filter}
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
