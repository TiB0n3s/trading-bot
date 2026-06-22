"""Persistence helpers for the paper discovery execution bridge."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from db import DB_PATH, get_connection

from repositories import auto_buy_repo

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
    ) -> list[dict[str, Any]]:
        timestamp_filter = ""
        latest_timestamp_filter = ""
        fresh_filter = ""
        params: list[Any] = [min_score]
        if target_date:
            timestamp_filter = "AND substr(snap.candidate_timestamp, 1, 10) = ?"
            latest_timestamp_filter = "AND substr(latest.candidate_timestamp, 1, 10) = ?"
            params.append(target_date)
            params.append(target_date)
        if min_candidate_timestamp:
            fresh_filter = "AND snap.candidate_timestamp >= ?"
            params.append(min_candidate_timestamp)
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

    def stale_routing_rows(self, *, stale_cutoff: str) -> list[dict[str, Any]]:
        """Rows stuck in ROUTING whose claim is older than ``stale_cutoff``.

        A crash between claim_candidates (which commits ROUTING) and mark_routed
        leaves a row in ROUTING permanently. These are candidates for the
        reclaim sweeper to reconcile against the broker.
        """
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT id, symbol, candidate_timestamp, score, candidate_json,
                       execution_attempted_at
                FROM auto_buy_decision_snapshots
                WHERE execution_status = ?
                  AND execution_attempted_at IS NOT NULL
                  AND execution_attempted_at < ?
                ORDER BY execution_attempted_at ASC
                """,
                (ROUTING, stale_cutoff),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_recent_routed_candidate(
        self,
        *,
        symbol: str,
        recent_route_cutoff: str,
    ) -> dict[str, Any] | None:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT id, candidate_timestamp, routed_order_id, order_id
                FROM auto_buy_decision_snapshots
                WHERE symbol = ?
                  AND execution_status = ?
                  AND candidate_timestamp >= ?
                ORDER BY candidate_timestamp DESC, id DESC
                LIMIT 1
                """,
                (symbol, ROUTED, recent_route_cutoff),
            ).fetchone()
        return dict(row) if row else None

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

    def mark_retryable(self, *, candidate_id: int, reason: str) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                UPDATE auto_buy_decision_snapshots
                SET execution_status = ?,
                    execution_completed_at = ?,
                    execution_error = ?,
                    order_submitted = 0,
                    routed_order_id = NULL,
                    order_id = NULL,
                    order_status = NULL
                WHERE id = ?
                """,
                (PENDING, _now_iso(), reason, candidate_id),
            )

    def record_routed_buy_trade(
        self,
        *,
        candidate: dict[str, Any],
        order: dict[str, Any],
        position_size_pct: float,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> bool:
        order_id = _order_identifier(order)
        if not order_id or auto_buy_repo.trade_order_exists(order_id, self.db_path):
            return False

        raw_qty = order.get("qty")
        try:
            qty = int(float(raw_qty)) if raw_qty not in (None, "") else None
        except (TypeError, ValueError):
            qty = None

        order_for_ledger = dict(order)
        order_for_ledger["order_id"] = order_id
        order_for_ledger.setdefault("status", order.get("status") or "submitted")
        order_for_ledger.setdefault(
            "current_price",
            _order_signal_price(order_for_ledger, candidate, stop_loss_pct),
        )
        auto_buy_repo.insert_auto_buy_trade(
            timestamp=datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S"),
            candidate=candidate,
            order=order_for_ledger,
            qty=qty,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            db_path=self.db_path,
        )
        return True


def _order_identifier(order: dict[str, Any]) -> str | None:
    for key in ("order_id", "id", "client_order_id"):
        value = order.get(key)
        if value:
            return str(value)
    return None


def _order_signal_price(
    order: dict[str, Any],
    candidate: dict[str, Any],
    stop_loss_pct: float,
) -> float | None:
    for value in (
        order.get("current_price"),
        candidate.get("signal_price"),
        candidate.get("current_price"),
        candidate.get("close"),
        candidate.get("ask"),
        candidate.get("bid"),
    ):
        try:
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue

    stop_loss = order.get("stop_loss")
    try:
        if stop_loss not in (None, "") and stop_loss_pct < 100:
            return round(float(stop_loss) / (1 - stop_loss_pct / 100), 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None
