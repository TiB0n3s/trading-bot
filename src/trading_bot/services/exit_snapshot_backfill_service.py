"""Historical repair service for canonical exit snapshots.

This service is analysis-only. It backfills canonical exit snapshot rows from
already-matched historical trades and never touches broker/order behavior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from repositories.exit_snapshot_repo import ExitSnapshotRepository
from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.canonical_exit_service import build_canonical_exit_snapshot
from services.exit_snapshot_service import ExitSnapshotService
from services.lifecycle_analysis_service import LifecycleAnalysisService


@dataclass(frozen=True)
class ExitSnapshotBackfillResult:
    scanned: int
    inserted: int
    dry_run: bool
    start_date: str
    end_date: str
    samples: list[dict[str, Any]]


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _missed_upside_pct(mfe_pct: float | None, realized_pct: float | None) -> float | None:
    if mfe_pct is None or realized_pct is None:
        return None
    return max(0.0, mfe_pct - realized_pct)


def _dedupe_key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (
        row.get("decision_snapshot_id"),
        row.get("entry_trade_id") or row.get("trade_id"),
        row.get("matched_trade_id"),
    )


class ExitSnapshotBackfillService:
    def __init__(
        self,
        repository: ExitSnapshotRepository | None = None,
        exit_snapshot_service: ExitSnapshotService | None = None,
    ):
        self.repository = repository or ExitSnapshotRepository()
        self.exit_snapshot_service = exit_snapshot_service or ExitSnapshotService(self.repository)

    def backfill_approved_matched_exits(
        self,
        *,
        start_date: str,
        end_date: str | None = None,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> ExitSnapshotBackfillResult:
        end_date = end_date or start_date
        try:
            rows = self.repository.approved_matched_exit_rows_missing_snapshots(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        except Exception:
            rows = []
        row_items = [dict(row) for row in rows]
        seen = {_dedupe_key(row) for row in row_items}
        if limit is None or len(row_items) < int(limit):
            remaining_limit = None if limit is None else max(0, int(limit) - len(row_items))
            for trade_row in self.repository.approved_trade_rows_missing_snapshots(
                start_date=start_date,
                end_date=end_date,
                limit=remaining_limit,
            ):
                item = dict(trade_row)
                key = _dedupe_key(item)
                if key in seen:
                    continue
                row_items.append(item)
                seen.add(key)
                if remaining_limit is not None and len(row_items) >= int(limit):
                    break
            lifecycle_rows = []
            try:
                lifecycle_payload = LifecycleAnalysisService(
                    LifecycleAnalysisRepository(self.repository.db_path)
                ).payload(start_date=start_date, end_date=end_date)
                lifecycle_rows = lifecycle_payload.rows
            except Exception:
                lifecycle_rows = []
            for lifecycle_row in lifecycle_rows:
                item = dict(lifecycle_row)
                if item.get("lifecycle_status") != "approved_matched_exit_missing_snapshot":
                    continue
                key = _dedupe_key(item)
                if key in seen:
                    continue
                row_items.append(item)
                seen.add(key)
                if remaining_limit is not None and len(row_items) >= int(limit):
                    break

        inserted = 0
        samples: list[dict[str, Any]] = []
        for item in row_items:
            realized_pct = _float(item.get("realized_return_pct"))
            mfe_pct = _float(item.get("mfe_pct"))
            snapshot = build_canonical_exit_snapshot(
                symbol=item.get("symbol"),
                exit_ts=item.get("exit_timestamp"),
                exit_trigger="matched_trade_exit",
                exit_source="historical_exit_snapshot_backfill",
                decision_snapshot_id=item.get("decision_snapshot_id"),
                entry_trade_id=item.get("entry_trade_id") or item.get("trade_id"),
                matched_trade_id=item.get("matched_trade_id"),
                position_id=item.get("entry_order_id") or item.get("trade_order_id"),
                exit_order_id=item.get("exit_order_id") or item.get("matched_exit_order_id"),
                entry_canonical_intelligence_version=item.get(
                    "entry_canonical_intelligence_version"
                ),
                entry_canonical_intelligence_hash=item.get("entry_canonical_intelligence_hash"),
                canonical_intelligence=_json_dict(item.get("canonical_intelligence_json")),
                realized_outcome={
                    "realized_pnl": _float(item.get("realized_pnl")),
                    "realized_return_pct": realized_pct,
                    "mfe_pct": mfe_pct,
                    "capture_ratio": _float(item.get("capture_ratio")),
                    "holding_minutes": _float(item.get("holding_minutes")),
                    "entry_price": _float(item.get("matched_entry_price"))
                    or _float(item.get("trade_fill_price")),
                    "exit_price": _float(item.get("exit_price")),
                    "exit_qty": _float(item.get("exit_qty")) or _float(item.get("trade_qty")),
                },
                foregone_outcome={
                    "missed_upside_pct": _missed_upside_pct(mfe_pct, realized_pct),
                    "avoided_drawdown_pct": None,
                },
                post_exit_path={
                    "return_30m_pct": None,
                    "return_60m_pct": None,
                    "reentry_window_summary": "not_available_historical_backfill",
                },
                trigger_metadata={
                    "matched_exit_reason": item.get("exit_reason"),
                    "entry_order_id": item.get("entry_order_id") or item.get("trade_order_id"),
                    "exit_order_id": item.get("exit_order_id") or item.get("matched_exit_order_id"),
                    "repair_scope": "approved_matched_exit_missing_snapshot",
                },
            )

            samples.append(
                {
                    "decision_snapshot_id": item.get("decision_snapshot_id"),
                    "matched_trade_id": item.get("matched_trade_id"),
                    "symbol": item.get("symbol"),
                    "exit_timestamp": item.get("exit_timestamp"),
                    "canonical_exit_hash": snapshot.exit_snapshot_hash,
                }
            )
            if not dry_run:
                self.exit_snapshot_service.persist(snapshot)
                inserted += 1

        return ExitSnapshotBackfillResult(
            scanned=len(row_items),
            inserted=inserted,
            dry_run=dry_run,
            start_date=start_date,
            end_date=end_date,
            samples=samples[:20],
        )
