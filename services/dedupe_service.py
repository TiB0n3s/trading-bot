"""Webhook dedupe key generation and persistence adapters."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from repositories import cooldown_repo


def make_dedupe_key(data: dict[str, Any]) -> str:
    """Create a stable dedupe key for repeated webhook deliveries."""
    explicit = (
        data.get("alert_id")
        or data.get("id")
        or data.get("uuid")
        or data.get("webhook_id")
    )
    if explicit:
        return f"explicit:{str(explicit).strip()}"

    normalized = {
        "symbol": str(data.get("symbol", "")).upper(),
        "action": str(data.get("action", "")).lower(),
        "price": str(data.get("price", "")),
        "source": str(data.get("source", "")),
        "timestamp": str(
            data.get("timestamp")
            or data.get("time")
            or data.get("alert_time")
            or data.get("alert_timestamp")
            or ""
        ),
    }

    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return "hash:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_webhook_event(dedupe_key: str, data: dict[str, Any], dedupe_seconds: int) -> bool:
    return cooldown_repo.record_webhook_event(dedupe_key, data, dedupe_seconds)


def mark_webhook_event_status(
    dedupe_key: str,
    status: str,
    *,
    order_id: str | None = None,
    client_order_id: str | None = None,
    failure_reason: str | None = None,
) -> None:
    cooldown_repo.mark_webhook_event_status(
        dedupe_key,
        status,
        order_id=order_id,
        client_order_id=client_order_id,
        failure_reason=failure_reason,
    )
