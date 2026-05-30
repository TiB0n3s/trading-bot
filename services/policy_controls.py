"""Runtime policy-family kill switches."""

from __future__ import annotations

import os

from services.observability import record_policy_kill_switch


POLICY_FAMILIES = ("entry", "sizing", "execution", "exits", "reporting")


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def disabled_policy_families() -> set[str]:
    raw = os.getenv("DISABLED_POLICY_FAMILIES", "")
    return {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }


def policy_family_enabled(policy_family: str) -> bool:
    family = str(policy_family or "").strip().lower()
    env_name = f"POLICY_{family.upper()}_ENABLED"
    enabled = _truthy(os.getenv(env_name), default=True)
    if family in disabled_policy_families():
        enabled = False
    record_policy_kill_switch(family, enabled)
    return enabled


def public_policy_control_config() -> dict:
    disabled = disabled_policy_families()
    return {
        family: {
            "enabled": policy_family_enabled(family),
            "env": f"POLICY_{family.upper()}_ENABLED",
            "disabled_by_family_list": family in disabled,
        }
        for family in POLICY_FAMILIES
    }
