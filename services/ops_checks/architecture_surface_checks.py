"""Operator report for architecture surface cleanup progress."""

from __future__ import annotations

from pathlib import Path

from services.architecture_surface_audit_service import build_architecture_surface_payload


def run_architecture_surface_report(*, base_dir: Path) -> bool:
    payload = build_architecture_surface_payload(base_dir=base_dir)

    print()
    print("=" * 72)
    print("  Architecture Surface Audit")
    print("=" * 72)
    print(f"report_version          : {payload['version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"over_target_count       : {payload['over_target_count']}")
    print(f"raw_env_files           : {payload['raw_env_files']}")
    print(f"raw_env_keys            : {payload['raw_env_keys']}")
    print(f"compatibility_plan      : {payload['compatibility_plan_exists']}")

    print()
    print("Surface counts")
    print(f"  {'metric':<30} {'current':>8} {'target':>8} {'over':>8} {'status'}")
    for row in payload["surface_metrics"]:
        print(
            f"  {row['name']:<30} {row['current']:>8} "
            f"{row['target']:>8} {row['over_target']:>8} {row['status']}"
        )

    print()
    print("Large decision surfaces")
    print(f"  {'path':<42} {'lines':>7} {'target':>7} {'over':>7} {'status'}")
    for row in payload["large_files"]:
        print(
            f"  {row['path']:<42} {row['lines']:>7} "
            f"{row['target']:>7} {row['over_target']:>7} {row['status']}"
        )

    print()
    print("Largest Python files")
    for row in payload["top_python_files"]:
        print(f"  {row['path']:<58} {row['lines']}")

    print()
    print("Top raw env access files")
    for file_name, count in payload["top_env_access_files"]:
        print(f"  {file_name:<58} {count}")

    skeleton = payload["src_skeleton"]
    print()
    print("src/trading_bot skeleton")
    print(
        f"  root_exists={skeleton['root_exists']} "
        f"contexts_ready={skeleton['contexts_ready']}/{skeleton['contexts_expected']}"
    )
    missing = [
        item["name"]
        for item in skeleton["contexts"]
        if not item["exists"] or not item["init_exists"]
    ]
    if missing:
        print(f"  missing={','.join(missing)}")
    else:
        print("  missing=-")

    print()
    if payload["ready"]:
        print("[OK] architecture surface is within current targets")
        return True
    print("[WARN] architecture surface exceeds cleanup targets")
    return False
