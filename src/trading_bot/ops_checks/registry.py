"""Aggregated command registry for operator checks."""

from __future__ import annotations

from trading_bot.ops_checks.commands import COMMAND_GROUPS
from trading_bot.ops_checks.commands.base import HandlerMap, OpsCommandSpec


def _build_command_specs() -> dict[str, OpsCommandSpec]:
    specs: dict[str, OpsCommandSpec] = {}
    duplicates: set[str] = set()
    for group in COMMAND_GROUPS:
        for command, command_spec in group.items():
            if command in specs:
                duplicates.add(command)
            specs[command] = command_spec
    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise RuntimeError(f"duplicate ops_check command specs: {duplicate_list}")
    return specs


OPS_COMMAND_SPECS: dict[str, OpsCommandSpec] = _build_command_specs()


def build_command_args(argv: list[str], target_date: str) -> dict[str, object]:
    return {
        "target_date": target_date,
        "job_filter": argv[2] if len(argv) > 2 else None,
        "end_date": argv[3] if len(argv) > 3 and not argv[3].startswith("--") else target_date,
        "symbol_arg": argv[2] if len(argv) > 2 else "",
        "start_arg": argv[2] if len(argv) > 2 and not argv[2].startswith("--") else None,
        "optional_date_arg": argv[2] if len(argv) > 2 else None,
    }


__all__ = [
    "HandlerMap",
    "OPS_COMMAND_SPECS",
    "OpsCommandSpec",
    "build_command_args",
]
