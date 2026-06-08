"""Grouped ops-check command specs."""

from __future__ import annotations

from trading_bot.ops_checks.commands import (
    architecture,
    config,
    learning,
    market_data,
    portfolio,
    predictions,
    runtime,
)

COMMAND_GROUPS = (
    runtime.COMMAND_SPECS,
    architecture.COMMAND_SPECS,
    config.COMMAND_SPECS,
    learning.COMMAND_SPECS,
    market_data.COMMAND_SPECS,
    portfolio.COMMAND_SPECS,
    predictions.COMMAND_SPECS,
)
