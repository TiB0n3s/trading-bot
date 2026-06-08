#!/usr/bin/env python3
"""Contract tests for the ops_check command registry."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ops_check  # noqa: E402
from trading_bot.ops_checks.registry import OPS_COMMAND_SPECS, build_command_args  # noqa: E402


def test_ops_command_registry_handlers_exist():
    missing = [
        f"{command}:{spec.handler_name}"
        for command, spec in OPS_COMMAND_SPECS.items()
        if not hasattr(ops_check, spec.handler_name)
    ]

    assert missing == []


def test_ops_command_registry_uses_known_argument_tokens():
    args = build_command_args(["ops_check.py", "runtime-health"], "2026-06-08")
    missing = [
        f"{command}:{token}"
        for command, spec in OPS_COMMAND_SPECS.items()
        for token in spec.arg_tokens
        if token not in args
    ]

    assert missing == []


def test_ops_command_registry_covers_high_value_commands():
    expected = {
        "jobs",
        "resource-readiness",
        "volume-clock-vpin",
        "historical-bar-readiness",
        "transformer-authority",
        "paper-learning-authority",
    }

    assert expected.issubset(OPS_COMMAND_SPECS)


def main():
    tests = [
        test_ops_command_registry_handlers_exist,
        test_ops_command_registry_uses_known_argument_tokens,
        test_ops_command_registry_covers_high_value_commands,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} ops check registry tests passed.")


if __name__ == "__main__":
    main()
