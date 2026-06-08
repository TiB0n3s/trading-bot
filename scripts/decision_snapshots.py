#!/usr/bin/env python3
"""Point-in-time decision snapshot helpers.

Snapshots are append-only audit rows. They intentionally duplicate selected
trade/context fields so historical replay does not have to consult mutable
runtime files for what the bot knew at decision time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.decision_snapshot_service import (
    build_default_decision_snapshot_service,
    file_sha256,
    json_dumps,
)

BASE_DIR = Path(__file__).resolve().parent
MARKET_CONTEXT_PATH = BASE_DIR / "market_context.json"

_services: dict[str, Any] = {}


def _json_dumps(value: Any) -> str:
    return json_dumps(value)


def _service_for(db_path: Path | str | None):
    key = str(db_path or "__default__")
    if key not in _services:
        _services[key] = build_default_decision_snapshot_service(
            db_path=db_path,
            base_dir=BASE_DIR,
        )
    return _services[key]


def _git_sha() -> str | None:
    return _service_for(None).git_sha()


def _file_sha256(path: Path) -> str | None:
    return file_sha256(path)


def _market_context_metadata(path: Path = MARKET_CONTEXT_PATH) -> dict[str, Any]:
    return _service_for(None).market_context_metadata(path)


def env_profile_hash() -> str:
    return _service_for(None).env_profile_hash()


def record_decision_snapshot(
    *,
    trade_id: int | None,
    timestamp: str,
    source: str,
    symbol: str | None,
    action: str | None,
    signal_price: float | None,
    decision: dict[str, Any] | None,
    order: dict[str, Any] | None,
    context: dict[str, Any] | None,
    account_state: dict[str, Any] | None = None,
    raw_signal: dict[str, Any] | None = None,
    rejection_reason: str | None = None,
    db_path: Path | str | None = None,
) -> int:
    """Insert one immutable audit snapshot and return its id."""
    return _service_for(db_path).record_decision_snapshot(
        trade_id=trade_id,
        timestamp=timestamp,
        source=source,
        symbol=symbol,
        action=action,
        signal_price=signal_price,
        decision=decision,
        order=order,
        context=context,
        account_state=account_state,
        raw_signal=raw_signal,
        rejection_reason=rejection_reason,
    )


def summarize_snapshots(
    target_date: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    return _service_for(db_path).summarize_snapshots(target_date)
