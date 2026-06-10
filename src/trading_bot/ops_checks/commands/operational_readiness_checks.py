"""Aggregated operational readiness report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.operational_readiness_service import build_operational_readiness_payload

from ops.deployment_reference_audit import audit_deployment_references


def _missing_refs(base_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for item in audit_deployment_references(base_dir):
        rows.append(
            {
                "source": item.source,
                "line_no": item.line_no,
                "reference": item.reference,
                "suggested_path": item.suggested_path,
            }
        )
    return rows


def run_operational_readiness(
    target_date: str,
    *,
    base_dir: Path,
    env_file: Path = Path("/etc/trading-bot.env"),
    max_backup_age_hours: float = 30.0,
    max_wal_bytes: int = 512 * 1024 * 1024,
    require_job_ledger: bool = True,
) -> bool:
    payload = build_operational_readiness_payload(
        base_dir=base_dir,
        target_date=target_date,
        env_file=env_file,
        max_backup_age_hours=max_backup_age_hours,
        max_wal_bytes=max_wal_bytes,
        require_job_ledger=require_job_ledger,
        missing_deployment_references=_missing_refs(base_dir),
    )

    print()
    print("=" * 72)
    print(f"  Operational Readiness — {target_date}")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"ready                   : {payload['ready']}")
    print(f"check_count             : {payload['check_count']}")
    print(f"critical_failure_count  : {payload['critical_failure_count']}")
    print(f"warning_count           : {payload['warning_count']}")
    print()
    print(f"  {'check':<28} {'status':<7} {'severity':<9} summary")
    for check in payload["checks"]:
        print(
            f"  {check['name']:<28} {check['status']:<7} {check['severity']:<9} {check['summary']}"
        )
    failures = [row for row in payload["checks"] if row["status"] == "fail"]
    warnings = [row for row in payload["checks"] if row["status"] == "warn"]
    if failures:
        print()
        print("Critical details")
        for row in failures[:8]:
            print(f"  {row['name']}: {row['detail']}")
    if warnings:
        print()
        print("Warning details")
        for row in warnings[:8]:
            print(f"  {row['name']}: {row['detail']}")
    print()
    if payload["ready"]:
        print("[OK] operational readiness has no critical blockers")
        return True
    print("[FAIL] operational readiness has critical blockers")
    return False
