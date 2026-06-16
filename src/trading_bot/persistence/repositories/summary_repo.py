"""Repository reads for daily and weekly summary reports."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection

TRADE_CONTEXT_COLUMNS = """
    id,
    timestamp,
    symbol,
    action,
    approved,
    rejection_reason,
    confidence,
    setup_label,
    setup_policy_action,
    setup_policy_reason
"""


class SummaryRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def trades_for_day(self, target_date: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                "SELECT * FROM trades WHERE timestamp LIKE ?",
                (f"{target_date}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    def trades_for_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT *
                FROM trades
                WHERE timestamp >= ? AND timestamp < ?
                """,
                (start_date, end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def trade_context_rows_for_day(self, target_date: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT {TRADE_CONTEXT_COLUMNS}
                FROM trades
                WHERE timestamp LIKE ?
                ORDER BY timestamp ASC
                """,
                (f"{target_date}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    def trade_context_rows_for_range(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT {TRADE_CONTEXT_COLUMNS}
                FROM trades
                WHERE timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (start_date, end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def auto_buy_hard_block_audit_for_day(self, target_date: str) -> dict[str, Any]:
        return self._auto_buy_hard_block_audit(
            "substr(candidate_timestamp, 1, 10) = ?",
            (target_date,),
        )

    def auto_buy_hard_block_audit_for_range(
        self,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        return self._auto_buy_hard_block_audit(
            "candidate_timestamp >= ? AND candidate_timestamp < ?",
            (start_date, end_date),
        )

    def _auto_buy_hard_block_audit(self, where_clause: str, params) -> dict[str, Any]:
        empty = {
            "rows_seen": 0,
            "hard_blocked_rows": 0,
            "counterfactual_strong_rows": 0,
            "counterfactual_watch_rows": 0,
            "by_reason": [],
            "top_counterfactual_strong": [],
        }
        try:
            with get_connection(self.db_path) as con:
                rows = con.execute(
                    f"""
                    SELECT
                        candidate_timestamp,
                        symbol,
                        decision,
                        score,
                        hard_block_reason,
                        candidate_json
                    FROM auto_buy_decision_snapshots
                    WHERE {where_clause}
                    ORDER BY candidate_timestamp ASC, id ASC
                    """,
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            return empty

        reason_groups: dict[str, dict[str, Any]] = {}
        top_counterfactual: list[dict[str, Any]] = []
        hard_blocked_rows = 0
        counterfactual_strong_rows = 0
        counterfactual_watch_rows = 0

        for row in rows:
            candidate = _json_object(row["candidate_json"])
            hard_block_reason = (
                row["hard_block_reason"]
                or candidate.get("hard_block_audit_reason")
                or candidate.get("hard_block_reason")
                or ""
            )
            reasons = _audit_reasons(candidate, hard_block_reason)
            if not reasons:
                continue

            hard_blocked_rows += 1
            audit_decision = str(
                candidate.get("hard_block_audit_decision_without_hard_blocks") or ""
            )
            would_be_strong = (
                bool(candidate.get("hard_block_audit_would_be_strong_candidate"))
                or audit_decision == "strong_buy_candidate"
            )
            would_be_watch = audit_decision == "watch"
            if would_be_strong:
                counterfactual_strong_rows += 1
            if would_be_watch:
                counterfactual_watch_rows += 1

            score = _to_float(row["score"])
            primary = _primary_hard_block_reason(reasons[0])
            group = reason_groups.setdefault(
                primary,
                {
                    "reason": primary,
                    "rows": 0,
                    "counterfactual_strong_rows": 0,
                    "counterfactual_watch_rows": 0,
                    "score_sum": 0.0,
                    "score_count": 0,
                    "max_score": None,
                },
            )
            group["rows"] += 1
            if would_be_strong:
                group["counterfactual_strong_rows"] += 1
            if would_be_watch:
                group["counterfactual_watch_rows"] += 1
            if score is not None:
                group["score_sum"] += score
                group["score_count"] += 1
                if group["max_score"] is None or score > group["max_score"]:
                    group["max_score"] = score

            if would_be_strong:
                top_counterfactual.append(
                    {
                        "timestamp": row["candidate_timestamp"],
                        "symbol": row["symbol"],
                        "score": score,
                        "final_decision": row["decision"],
                        "counterfactual_decision": audit_decision,
                        "primary_reason": primary,
                        "hard_block_reason": hard_block_reason,
                    }
                )

        by_reason = []
        for group in reason_groups.values():
            score_count = int(group.pop("score_count"))
            score_sum = float(group.pop("score_sum"))
            group["avg_score"] = score_sum / score_count if score_count else None
            by_reason.append(group)
        by_reason.sort(
            key=lambda item: (
                int(item["counterfactual_strong_rows"]),
                int(item["rows"]),
                float(item["max_score"] if item["max_score"] is not None else -9999),
            ),
            reverse=True,
        )
        top_counterfactual.sort(
            key=lambda item: float(item["score"] if item["score"] is not None else -9999),
            reverse=True,
        )

        return {
            "rows_seen": len(rows),
            "hard_blocked_rows": hard_blocked_rows,
            "counterfactual_strong_rows": counterfactual_strong_rows,
            "counterfactual_watch_rows": counterfactual_watch_rows,
            "by_reason": by_reason[:12],
            "top_counterfactual_strong": top_counterfactual[:10],
        }

    def matched_trades_for_day(self, target_date: str) -> list[dict[str, Any]]:
        return self._matched_trades(
            "AND exit_timestamp LIKE ?",
            (f"{target_date}%",),
        )

    def matched_trades_for_range(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        return self._matched_trades(
            "AND exit_timestamp >= ? AND exit_timestamp < ?",
            (start_date, end_date),
        )

    def _matched_trades(self, extra_where: str, params) -> list[dict[str, Any]]:
        try:
            with get_connection(self.db_path) as con:
                rows = con.execute(
                    f"""
                    SELECT symbol, qty, entry_price, exit_price, realized_pnl, won
                    FROM matched_trades
                    WHERE 1=1 {extra_where}
                    ORDER BY exit_timestamp ASC
                    """,
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            return []

        return [dict(row) for row in rows]


def _json_object(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _audit_reasons(candidate: dict[str, Any], fallback: str) -> list[str]:
    raw_reasons = candidate.get("hard_block_audit_reasons")
    if isinstance(raw_reasons, list):
        reasons = [str(item).strip() for item in raw_reasons if str(item).strip()]
        if reasons:
            return reasons
    return [part.strip() for part in str(fallback or "").split(";") if part.strip()]


def _primary_hard_block_reason(reason: str) -> str:
    reason = str(reason or "").strip()
    if not reason:
        return "unknown"
    return reason.split(":", 1)[0].strip() or "unknown"


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
