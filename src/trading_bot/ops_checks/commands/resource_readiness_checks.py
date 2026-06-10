"""Operator report for optional VM resource readiness."""

from __future__ import annotations

from pathlib import Path

from services.vm_resource_readiness_service import vm_resource_readiness


def run_resource_readiness(*, base_dir: Path) -> bool:
    payload = vm_resource_readiness()

    print()
    print("=" * 72)
    print("  VM Resource Readiness")
    print("=" * 72)
    print(f"report_version          : {payload['version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"configured_resources    : {payload['configured_count']}/{payload['total_count']}")

    print()
    print("Category readiness")
    for category, counts in sorted(payload["by_category"].items()):
        print(f"  {category:<24} {counts['configured']:>2}/{counts['total']:<2}")

    print()
    print("Resources")
    print(f"  {'resource':<34} {'status':<15} {'missing'}")
    print(f"  {'-' * 34} {'-' * 15} {'-' * 34}")
    for row in payload["resources"]:
        missing = list(row["env"]["missing"]) + list(row["packages"]["missing"])
        missing_s = ", ".join(missing) if missing else "-"
        print(f"  {row['key']:<34} {row['status']:<15} {missing_s}")

    print()
    print("Next actions")
    for row in payload["resources"]:
        if row["configured"]:
            continue
        print(f"  - {row['label']}: {row['next_action']}")

    print()
    print("[OK] resource readiness inventory completed")
    return True
