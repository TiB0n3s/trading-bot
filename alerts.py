#!/usr/bin/env python3
"""
Fail-open external alert helper.

Notification-only:
- does not approve/reject trades
- does not place/cancel orders
- never raises back into trading flow

Enable with:
  ALERTS_ENABLED=true
  ALERT_WEBHOOK_URL=https://...
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any


SEVERITY_RANK = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "critical": 50,
}


def alerts_enabled() -> bool:
    return os.getenv("ALERTS_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def alert_config_public() -> dict[str, Any]:
    url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    return {
        "alerts_enabled": alerts_enabled(),
        "alert_webhook_configured": bool(url),
        "alert_min_severity": os.getenv("ALERT_MIN_SEVERITY", "warning").strip().lower(),
    }


def _severity_allowed(severity: str) -> bool:
    severity = str(severity or "info").strip().lower()
    minimum = os.getenv("ALERT_MIN_SEVERITY", "warning").strip().lower()
    return SEVERITY_RANK.get(severity, 20) >= SEVERITY_RANK.get(minimum, 30)


def send_alert(
    *,
    title: str,
    message: str,
    severity: str = "warning",
    source: str | None = None,
    symbol: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 4.0,
) -> bool:
    """Send a generic JSON webhook alert. Fail-open."""
    try:
        if not alerts_enabled() or not _severity_allowed(severity):
            return False

        url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
        if not url:
            return False

        body = {
            "title": title,
            "message": message,
            "severity": severity,
            "source": source,
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }

        data = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300

    except Exception:
        return False
