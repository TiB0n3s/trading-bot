"""Canonical per-exit state snapshot construction.

This module is intentionally audit-only. It does not decide exits or alter
broker/order behavior; it creates a stable substrate for exit learning,
counterfactual review, and replay.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from services.canonical_intelligence_service import (
    stable_canonical_hash,
    stable_canonical_json,
)


CANONICAL_EXIT_VERSION = "canonical_exit_v1"
CANONICAL_EXIT_REQUIRED_SECTIONS = (
    "exit_identity",
    "exit_trigger",
    "canonical_intelligence_state",
    "realized_outcome",
    "foregone_outcome",
    "post_exit_path",
)
CANONICAL_EXIT_MAX_JSON_BYTES = 16_384


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _canonical_intelligence_state(canonical_intelligence: Any) -> dict[str, Any]:
    data = _dict(canonical_intelligence)
    if hasattr(canonical_intelligence, "to_dict"):
        data = canonical_intelligence.to_dict()

    # Keep the exit payload compact: preserve the immutable identity/hash and
    # the decision-relevant state summaries, not bulky raw upstream artifacts.
    return {
        "version": data.get("version"),
        "hash": data.get("feature_vector_hash")
        or data.get("canonical_intelligence_hash"),
        "feature_semantic_version": data.get("feature_semantic_version"),
        "decision_ts": data.get("decision_ts"),
        "source_timestamps": data.get("source_timestamps") or {},
        "freshness_sec": data.get("freshness_sec") or {},
        "confidence": data.get("confidence") or {},
        "regime_state": data.get("regime_state") or {},
        "momentum_state": data.get("momentum_state") or {},
        "trend_state": data.get("trend_state") or {},
        "prediction_state": data.get("prediction_state") or {},
        "setup_state": data.get("setup_state") or {},
    }


@dataclass(frozen=True)
class CanonicalExitSnapshot:
    version: str
    created_at: str
    symbol: str | None
    exit_ts: str | None
    exit_identity: dict[str, Any]
    exit_trigger: dict[str, Any]
    canonical_intelligence_state: dict[str, Any]
    realized_outcome: dict[str, Any]
    foregone_outcome: dict[str, Any]
    post_exit_path: dict[str, Any]
    exit_snapshot_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_canonical_exit_snapshot(
    *,
    symbol: str | None,
    exit_ts: str | None,
    exit_trigger: str | None,
    exit_source: str | None = None,
    exit_trade_id: int | None = None,
    matched_trade_id: int | None = None,
    exit_order_id: str | None = None,
    canonical_intelligence: Any = None,
    realized_outcome: dict[str, Any] | None = None,
    foregone_outcome: dict[str, Any] | None = None,
    post_exit_path: dict[str, Any] | None = None,
    trigger_metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> CanonicalExitSnapshot:
    exit_identity = {
        "symbol": symbol,
        "exit_ts": exit_ts,
        "exit_trade_id": exit_trade_id,
        "matched_trade_id": matched_trade_id,
        "exit_order_id": exit_order_id,
    }
    trigger_state = {
        "trigger": exit_trigger,
        "source": exit_source,
        "metadata": trigger_metadata or {},
    }
    intelligence_state = _canonical_intelligence_state(canonical_intelligence)
    realized = _dict(realized_outcome)
    foregone = _dict(foregone_outcome)
    post_exit = _dict(post_exit_path)

    hash_payload = {
        "exit_identity": exit_identity,
        "exit_trigger": trigger_state,
        "canonical_intelligence_state": intelligence_state,
        "realized_outcome": realized,
        "foregone_outcome": foregone,
        "post_exit_path": post_exit,
    }

    return CanonicalExitSnapshot(
        version=CANONICAL_EXIT_VERSION,
        created_at=created_at or _utc_now_iso(),
        symbol=symbol,
        exit_ts=exit_ts,
        exit_identity=exit_identity,
        exit_trigger=trigger_state,
        canonical_intelligence_state=intelligence_state,
        realized_outcome=realized,
        foregone_outcome=foregone,
        post_exit_path=post_exit,
        exit_snapshot_hash=stable_canonical_hash(hash_payload),
    )


def canonical_exit_json(snapshot: CanonicalExitSnapshot) -> str:
    return stable_canonical_json(snapshot.to_dict())


def canonical_exit_json_size_bytes(snapshot: CanonicalExitSnapshot) -> int:
    return len(canonical_exit_json(snapshot).encode("utf-8"))


def validate_canonical_exit_snapshot_contract(
    snapshot: CanonicalExitSnapshot,
) -> dict[str, Any]:
    data = snapshot.to_dict()
    missing_sections = [
        section
        for section in CANONICAL_EXIT_REQUIRED_SECTIONS
        if section not in data or not isinstance(data.get(section), dict)
    ]
    size_bytes = canonical_exit_json_size_bytes(snapshot)
    return {
        "ok": not missing_sections and size_bytes <= CANONICAL_EXIT_MAX_JSON_BYTES,
        "version": snapshot.version,
        "missing_sections": missing_sections,
        "json_size_bytes": size_bytes,
        "max_json_size_bytes": CANONICAL_EXIT_MAX_JSON_BYTES,
        "stable_hash": snapshot.exit_snapshot_hash,
    }
