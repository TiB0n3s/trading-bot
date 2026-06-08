"""Operator report for feature flag inventory."""

from __future__ import annotations

from pathlib import Path

from services.feature_flag_inventory_service import build_feature_flag_inventory


def run_feature_flag_inventory_report(
    *,
    base_dir: Path,
    limit: int = 40,
) -> bool:
    payload = build_feature_flag_inventory(base_dir=base_dir)

    print()
    print("=" * 72)
    print("  Feature Flag Inventory")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"flag_count              : {payload['flag_count']}")
    print(f"high_authority_count    : {payload['high_authority_count']}")
    print(f"metadata_count          : {payload['metadata_count']}")
    print(f"high_missing_metadata   : {payload['high_authority_missing_metadata_count']}")
    print(f"missing_rollback_count  : {payload['missing_rollback_count']}")

    print()
    print("Owners")
    for owner, count in payload["owners"].items():
        print(f"  {owner:<18} {count}")

    print()
    print("Flags")
    print(f"  {'name':<42} {'owner':<14} {'auth':<6} {'meta':<5} rollback")
    print(f"  {'-' * 42} {'-' * 14} {'-' * 6} {'-' * 5} {'-' * 24}")
    for row in payload["flags"][:limit]:
        print(
            f"  {row['name']:<42} {row['owner']:<14} "
            f"{row['authority_level']:<6} {str(row['metadata_present']):<5} "
            f"{row['rollback_action']}"
        )

    if len(payload["flags"]) > limit:
        print(f"  ... {len(payload['flags']) - limit} more")

    if payload["high_authority_missing_metadata"]:
        print()
        print("High-authority flags missing explicit metadata")
        for name in payload["high_authority_missing_metadata"][:limit]:
            print(f"  - {name}")

    print()
    if payload["ready"]:
        print("[OK] feature flag inventory generated")
        return True
    print("[WARN] feature flag inventory needs review")
    return False
