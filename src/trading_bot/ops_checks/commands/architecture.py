"""Architecture and package-boundary ops-check command specs."""

from __future__ import annotations

from trading_bot.ops_checks.commands.base import OpsCommandSpec, noarg

COMMAND_SPECS: dict[str, OpsCommandSpec] = {
    "architecture-surface": noarg("architecture-surface"),
}
