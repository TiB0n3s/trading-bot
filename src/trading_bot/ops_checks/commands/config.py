"""Configuration, feature-flag, and secrets ops-check command specs."""

from __future__ import annotations

from trading_bot.ops_checks.commands.base import OpsCommandSpec, noarg

COMMAND_SPECS: dict[str, OpsCommandSpec] = {
    "config-audit": noarg("config-audit"),
    "feature-flags": noarg("feature-flags"),
    "secrets-hygiene": noarg("secrets-hygiene"),
    "secrets-manager-readiness": noarg("secrets-manager-readiness"),
}
