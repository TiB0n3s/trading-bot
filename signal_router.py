#!/usr/bin/env python3
"""
Signal router helpers.

This module defines normalized signal-event helpers for the future thinner
app.py architecture.

It does not enqueue, approve, reject, or place orders yet.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


VALID_ACTIONS = {"buy", "sell"}


@dataclass
class SignalEvent:
    symbol: str
    action: str
    price: float
    source: str
    received_at: str
    raw: dict[str, Any]
    timestamp: str | None = None
    dedupe_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except Exception:
        return default


def normalize_signal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized dict from a raw signal payload."""
    payload = payload or {}

    symbol = str(payload.get("symbol") or "").strip().upper()
    action = str(payload.get("action") or "").strip().lower()
    source = str(payload.get("source") or "").strip()
    price = safe_float(payload.get("price"))

    timestamp = (
        payload.get("timestamp")
        or payload.get("time")
        or payload.get("alert_time")
        or payload.get("alert_timestamp")
    )

    return {
        "symbol": symbol,
        "action": action,
        "source": source,
        "price": price,
        "timestamp": str(timestamp).strip() if timestamp else None,
        "raw": dict(payload),
    }


def validate_signal_payload(
    payload: dict[str, Any],
    approved_symbols: set[str],
    required_source: str = "TradingPilotAI",
) -> tuple[bool, str, dict[str, Any]]:
    """
    Validate normalized payload shape.

    This is shape/source/symbol validation only. It does not apply risk gates.
    """
    normalized = normalize_signal_payload(payload)

    symbol = normalized["symbol"]
    action = normalized["action"]
    source = normalized["source"]
    price = normalized["price"]

    if not symbol:
        return False, "missing symbol", normalized

    if symbol not in approved_symbols:
        return False, f"symbol {symbol} not approved", normalized

    if action not in VALID_ACTIONS:
        return False, f"invalid action {action}", normalized

    if price is None or price <= 0:
        return False, f"invalid price {price}", normalized

    if source != required_source:
        return False, f"invalid source {source}", normalized

    return True, "valid", normalized


def make_dedupe_key(normalized: dict[str, Any]) -> str:
    """Create a stable dedupe key for a normalized signal."""
    explicit = (
        normalized.get("raw", {}).get("alert_id")
        or normalized.get("raw", {}).get("id")
        or normalized.get("raw", {}).get("uuid")
    )

    if explicit:
        return f"explicit:{str(explicit).strip()}"

    raw = json.dumps(
        {
            "symbol": normalized.get("symbol"),
            "action": normalized.get("action"),
            "price": normalized.get("price"),
            "source": normalized.get("source"),
            "timestamp": normalized.get("timestamp") or "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return "hash:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_signal_event(payload: dict[str, Any]) -> SignalEvent:
    """Build a SignalEvent from a raw payload without applying approval gates."""
    normalized = normalize_signal_payload(payload)
    dedupe_key = make_dedupe_key(normalized)

    return SignalEvent(
        symbol=normalized["symbol"],
        action=normalized["action"],
        price=float(normalized["price"] or 0),
        source=normalized["source"],
        timestamp=normalized["timestamp"],
        received_at=datetime.now(timezone.utc).isoformat(),
        raw=normalized["raw"],
        dedupe_key=dedupe_key,
    )
