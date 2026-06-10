"""Operator report for external secrets manager readiness."""

from __future__ import annotations

from services.secrets_manager_readiness_service import build_secrets_manager_readiness_payload


def run_secrets_manager_readiness_report() -> bool:
    payload = build_secrets_manager_readiness_payload()
    print()
    print("=" * 72)
    print("  Secrets Manager Readiness")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"provider                : {payload['provider']}")
    print(f"supported_provider      : {payload['supported_provider']}")
    print(f"external_provider       : {payload['external_provider']}")
    print(f"required_keys           : {payload['required_keys']}")
    print(f"missing_keys            : {payload['missing_keys']}")
    print(f"current_local_source    : {payload['current_local_source']}")
    print(f"next_action             : {payload['next_action']}")
    print()
    if payload["ready"]:
        print("[OK] external secrets manager metadata is configured")
        return True
    print("[WARN] external secrets manager metadata is not complete")
    return False
