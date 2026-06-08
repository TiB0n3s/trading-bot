"""Signal timestamp, freshness, and order identity helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def parse_signal_timestamp(data: dict[str, Any], *, log: Any) -> datetime | None:
    """Best-effort parse of an optional TradingView/client timestamp."""
    raw = (
        data.get("timestamp")
        or data.get("time")
        or data.get("alert_time")
        or data.get("alert_timestamp")
    )
    if not raw:
        return None

    try:
        if isinstance(raw, (int, float)):
            ts = float(raw) / 1000 if float(raw) > 10_000_000_000 else float(raw)
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        raw_s = str(raw).strip()
        if raw_s.isdigit():
            ts = float(raw_s) / 1000 if len(raw_s) > 10 else float(raw_s)
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        parsed = datetime.fromisoformat(raw_s.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception as exc:
        log.warning(f"Unable to parse signal timestamp {raw!r}: {exc}")
        return None


def signal_staleness(
    data: dict[str, Any],
    *,
    ttl_seconds: int,
    log: Any,
    now_utc: datetime | None = None,
) -> tuple[bool, float | None, str]:
    """Return (is_stale, age_seconds, reason). Missing timestamps are allowed."""
    ts = parse_signal_timestamp(data, log=log)
    if ts is None:
        return False, None, "no timestamp provided"

    now = now_utc or datetime.now(timezone.utc)
    age_seconds = (now - ts).total_seconds()

    if age_seconds < -30:
        return True, age_seconds, f"signal timestamp is {abs(age_seconds):.1f}s in the future"

    if age_seconds > ttl_seconds:
        return True, age_seconds, f"signal age {age_seconds:.1f}s exceeds TTL {ttl_seconds}s"

    return False, age_seconds, f"signal age {age_seconds:.1f}s within TTL"


def make_client_order_id(symbol: str, action: str, data: dict[str, Any]) -> str:
    """Create a stable Alpaca client_order_id for idempotent broker submission."""
    dedupe_key = str(data.get("_dedupe_key") or "")
    timestamp_hint = str(
        data.get("timestamp")
        or data.get("time")
        or data.get("alert_time")
        or data.get("alert_timestamp")
        or datetime.now(timezone.utc).isoformat()
    )

    raw = json.dumps(
        {
            "symbol": symbol,
            "action": action,
            "price": data.get("price"),
            "source": data.get("source"),
            "dedupe_key": dedupe_key,
            "timestamp": timestamp_hint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"tb-{symbol.lower()}-{action.lower()}-{digest}"
