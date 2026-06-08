"""Portfolio, risk, and trade-lifecycle ops-check command specs."""

from __future__ import annotations

from trading_bot.ops_checks.commands.base import OpsCommandSpec, spec

COMMAND_SPECS: dict[str, OpsCommandSpec] = {
    "rejection-summary": spec("rejection-summary"),
    "rejected-outcomes": spec("rejected-outcomes", "rejected_outcomes_health"),
    "auto-buy": spec("auto-buy", "auto_buy_health"),
    "portfolio-risk": spec("portfolio-risk"),
    "exit-snapshot-backfill": spec("exit-snapshot-backfill"),
    "exit-intelligence": spec("exit-intelligence"),
}
