#!/usr/bin/env python3
"""Tests for external observability and secrets-manager readiness reports."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.external_observability_readiness_service import (  # noqa: E402
    build_external_observability_readiness_payload,
)
from services.secrets_manager_readiness_service import (  # noqa: E402
    build_secrets_manager_readiness_payload,
)


def test_external_observability_readiness_reports_missing_destinations():
    payload = build_external_observability_readiness_payload(env={})

    assert payload["runtime_effect"] == "readiness_only_no_network_calls"
    assert payload["ready"] is False
    assert payload["total_count"] == 3
    assert any(row["name"] == "alert_delivery" for row in payload["categories"])


def test_secrets_manager_readiness_accepts_configured_vault_metadata():
    payload = build_secrets_manager_readiness_payload(
        env={
            "SECRET_MANAGER_PROVIDER": "vault",
            "VAULT_ADDR": "https://vault.example",
            "VAULT_TOKEN": "token-reference",
        }
    )

    assert payload["ready"] is True
    assert payload["provider"] == "vault"
    assert payload["runtime_effect"] == "readiness_only_no_secret_reads_or_network_calls"


def main():
    tests = [
        test_external_observability_readiness_reports_missing_destinations,
        test_secrets_manager_readiness_accepts_configured_vault_metadata,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} external readiness tests passed.")


if __name__ == "__main__":
    main()
