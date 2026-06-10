"""Operator report for incident escalation readiness."""

from __future__ import annotations

from pathlib import Path

from services.incident_escalation_readiness_service import (
    build_incident_escalation_readiness_payload,
)


def run_incident_escalation_readiness_report(*, base_dir: Path) -> bool:
    payload = build_incident_escalation_readiness_payload(base_dir=base_dir)
    print()
    print("=" * 72)
    print("  Incident Escalation Readiness")
    print("=" * 72)
    print(f"report_version              : {payload['report_version']}")
    print(f"runtime_effect              : {payload['runtime_effect']}")
    print(f"metadata_path               : {payload['metadata_path']}")
    print(f"contact_count               : {payload['contact_count']}")
    print(f"severity_rule_count         : {payload['severity_rule_count']}")
    print(f"cash_live_review_required   : {payload['cash_live_review_required']}")
    print(
        "alert_destinations         : "
        + (",".join(payload["alert_destinations"]) if payload["alert_destinations"] else "-")
    )
    print("missing                    : " + (",".join(payload["missing"]) or "-"))
    print()
    if payload["ready"]:
        print("[OK] incident escalation metadata is ready")
        return True
    print("[WARN] incident escalation metadata has blockers")
    return False
