"""External secrets manager readiness inventory."""

from __future__ import annotations

import os
from typing import Any


def build_secrets_manager_readiness_payload(
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    provider = str(env.get("SECRET_MANAGER_PROVIDER") or "local_env_file").strip().lower()
    provider_checks = {
        "vault": ["VAULT_ADDR", "VAULT_TOKEN"],
        "aws": ["AWS_REGION", "TRADING_BOT_SECRET_ID"],
        "gcp": ["GOOGLE_CLOUD_PROJECT", "TRADING_BOT_SECRET_ID"],
        "azure": ["AZURE_KEY_VAULT_URL"],
        "local_env_file": [],
    }
    required = provider_checks.get(provider, [])
    supported = provider in provider_checks
    missing = [name for name in required if not str(env.get(name) or "").strip()]
    external_provider = provider != "local_env_file"
    ready = supported and external_provider and not missing
    return {
        "report_version": "secrets_manager_readiness_v1",
        "runtime_effect": "readiness_only_no_secret_reads_or_network_calls",
        "provider": provider,
        "supported_provider": supported,
        "external_provider": external_provider,
        "required_keys": required,
        "missing_keys": missing,
        "ready": ready,
        "current_local_source": "/etc/trading-bot.env",
        "next_action": (
            "configure SECRET_MANAGER_PROVIDER plus provider-specific connection metadata"
            if not ready
            else "external secrets manager metadata configured; verify retrieval in a non-trading dry run"
        ),
    }
