"""Operator report for configuration inventory and validation."""

from __future__ import annotations

from pathlib import Path

from services.config_audit_service import build_config_audit_payload


def run_config_audit_report(*, base_dir: Path) -> bool:
    payload = build_config_audit_payload(base_dir=base_dir)

    print()
    print("=" * 72)
    print("  Configuration Audit")
    print("=" * 72)
    print(f"report_version          : {payload['version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"execution_mode          : {payload['execution_mode']}")
    print(f"live_trading_enabled    : {payload['live_trading_enabled']}")
    print(f"factory_failures        : {payload['factory_failures']}/{payload['factory_count']}")

    print()
    print("Typed config factories")
    for row in payload["factories"]:
        reason = row.get("reason") or "-"
        print(
            f"  {row['name']:<20} status={row['status']:<6} "
            f"fields={row['fields']:<3} reason={reason}"
        )

    inventory = payload["env_inventory"]
    print()
    print("Env inventory")
    print(f"  total_env_keys         : {inventory['total_env_keys']}")
    print(f"  sensitive_env_key_count: {inventory['sensitive_env_key_count']}")

    print()
    print("Top raw env access files")
    for file_name, count in inventory["top_files"]:
        print(f"  {file_name:<54} {count}")

    if inventory["non_literal_call_files"]:
        print()
        print("Non-literal env access files")
        for file_name in inventory["non_literal_call_files"]:
            print(f"  {file_name}")

    print()
    print("Warnings")
    if payload["warnings"]:
        for warning in payload["warnings"]:
            print(f"  - {warning}")
    else:
        print("  none")

    print()
    if payload["ready"]:
        print("[OK] configuration audit passed")
        return True
    print("[WARN] configuration audit found items to review")
    return False
