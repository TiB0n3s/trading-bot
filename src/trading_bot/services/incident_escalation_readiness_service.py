"""Incident escalation readiness metadata checks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _load_metadata(base_dir: Path) -> dict[str, Any]:
    path = base_dir / "ops" / "incident_escalation.yml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_incident_escalation_readiness_payload(
    *,
    base_dir: Path,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = env or dict(os.environ)
    metadata = _load_metadata(base_dir)
    contacts = metadata.get("contacts") if isinstance(metadata.get("contacts"), list) else []
    severities = (
        metadata.get("severity_rules") if isinstance(metadata.get("severity_rules"), dict) else {}
    )
    alert_destinations = [
        key
        for key in ("ALERT_WEBHOOK_URL", "SLACK_WEBHOOK_URL", "PAGERDUTY_ROUTING_KEY")
        if env.get(key)
    ]
    review_required = bool(metadata.get("cash_live_review_required"))
    missing = []
    if not contacts:
        missing.append("contacts")
    if not severities:
        missing.append("severity_rules")
    if not alert_destinations:
        missing.append("alert_destination_env")
    if not review_required:
        missing.append("cash_live_review_required")
    return {
        "report_version": "incident_escalation_readiness_v1",
        "runtime_effect": "readiness_only_no_alerts_sent",
        "metadata_path": str(base_dir / "ops" / "incident_escalation.yml"),
        "contact_count": len(contacts),
        "severity_rule_count": len(severities),
        "alert_destinations": alert_destinations,
        "cash_live_review_required": review_required,
        "missing": missing,
        "ready": not missing,
    }
