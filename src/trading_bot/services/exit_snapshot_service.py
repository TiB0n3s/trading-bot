"""Persistence service for canonical exit snapshots."""

from __future__ import annotations

from typing import Any

from repositories.exit_snapshot_repo import ExitSnapshotRepository
from services.canonical_exit_service import (
    CanonicalExitSnapshot,
    canonical_exit_json,
)
from services.canonical_intelligence_service import stable_canonical_json


class ExitSnapshotService:
    def __init__(self, repository: ExitSnapshotRepository | None = None):
        self.repository = repository or ExitSnapshotRepository()

    def persist(self, snapshot: CanonicalExitSnapshot) -> int:
        data = snapshot.to_dict()
        trigger = data.get("exit_trigger") or {}
        intelligence = data.get("canonical_intelligence_state") or {}
        realized = data.get("realized_outcome") or {}
        foregone = data.get("foregone_outcome") or {}
        post_exit = data.get("post_exit_path") or {}
        identity = data.get("exit_identity") or {}
        regime_state = intelligence.get("regime_state") or {}
        momentum_state = intelligence.get("momentum_state") or {}
        trend_state = intelligence.get("trend_state") or {}

        row: dict[str, Any] = {
            "created_at": data["created_at"],
            "decision_snapshot_id": identity.get("decision_snapshot_id"),
            "entry_trade_id": identity.get("entry_trade_id"),
            "exit_trade_id": identity.get("exit_trade_id"),
            "matched_trade_id": identity.get("matched_trade_id"),
            "position_id": identity.get("position_id"),
            "symbol": data.get("symbol"),
            "exit_timestamp": data.get("exit_ts"),
            "exit_trigger": trigger.get("trigger"),
            "exit_source": trigger.get("source"),
            "realized_pnl": realized.get("realized_pnl"),
            "realized_return_pct": realized.get("realized_return_pct"),
            "mfe_pct": realized.get("mfe_pct"),
            "capture_ratio": realized.get("capture_ratio"),
            "max_adverse_excursion_pct": realized.get("max_adverse_excursion_pct"),
            "avoided_drawdown_pct": foregone.get("avoided_drawdown_pct"),
            "missed_upside_pct": foregone.get("missed_upside_pct"),
            "post_exit_return_30m_pct": post_exit.get("return_30m_pct"),
            "post_exit_return_60m_pct": post_exit.get("return_60m_pct"),
            "reentry_window_summary": post_exit.get("reentry_window_summary"),
            "exit_regime_state_json": stable_canonical_json(regime_state),
            "exit_momentum_state_json": stable_canonical_json(momentum_state),
            "exit_trend_state_json": stable_canonical_json(trend_state),
            "canonical_exit_version": data["version"],
            "canonical_exit_hash": data["exit_snapshot_hash"],
            "canonical_exit_json": canonical_exit_json(snapshot),
            "canonical_intelligence_hash": intelligence.get("hash"),
            "entry_canonical_intelligence_version": identity.get(
                "entry_canonical_intelligence_version"
            ),
            "entry_canonical_intelligence_hash": identity.get("entry_canonical_intelligence_hash"),
        }
        return self.repository.insert_snapshot(row)
