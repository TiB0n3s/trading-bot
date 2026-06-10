"""Operator report for packaged runtime entrypoint validation."""

from __future__ import annotations

from pathlib import Path

from services.packaged_entrypoint_validation_service import (
    build_packaged_entrypoint_validation_payload,
)


def run_packaged_entrypoint_validation_report(*, base_dir: Path) -> bool:
    payload = build_packaged_entrypoint_validation_payload(base_dir=base_dir)
    print()
    print("=" * 72)
    print("  Packaged Entrypoint Validation")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"check_count             : {payload['check_count']}")
    print(f"failed_count            : {payload['failed_count']}")
    print()
    for row in payload["checks"]:
        status = "ok" if row["passed"] else "fail"
        print(f"  {row['name']:<38} {status:<5} {row['detail']}")
    print()
    if payload["ready"]:
        print("[OK] packaged entrypoints are importable")
        return True
    print("[WARN] packaged entrypoint validation found blockers")
    return False
