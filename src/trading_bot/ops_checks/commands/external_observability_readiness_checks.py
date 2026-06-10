"""Operator report for external observability readiness."""

from __future__ import annotations

from services.external_observability_readiness_service import (
    build_external_observability_readiness_payload,
)


def run_external_observability_readiness_report() -> bool:
    payload = build_external_observability_readiness_payload()
    print()
    print("=" * 72)
    print("  External Observability Readiness")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"configured_count        : {payload['configured_count']}/{payload['total_count']}")
    print()
    for row in payload["categories"]:
        missing = ", ".join(row["missing"]) if row["missing"] else "-"
        print(f"  {row['name']:<20} configured={str(row['configured']):<5} missing={missing}")
        if not row["configured"]:
            print(f"    next_action={row['next_action']}")
    print()
    if payload["ready"]:
        print("[OK] external observability prerequisites are configured")
        return True
    print("[WARN] external observability prerequisites are not complete")
    return False
