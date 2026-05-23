#!/usr/bin/env python3
"""
Strategy engine skeleton.

Future home for strategy-level decision orchestration.

For now this is observe-only scaffolding:
- normalizes inputs
- calls deterministic trader-brain scorer
- returns a structured strategy result
- does not approve, reject, size, or place orders
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from strategy.trade_scorer import score_trade


@dataclass
class StrategyResult:
    symbol: str
    action: str
    observe_only: bool
    trader_brain: dict[str, Any]
    final_decision: dict[str, Any] | None = None
    notes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_strategy_observe_only(
    symbol: str,
    action: str,
    account_state: dict[str, Any] | None = None,
    trend: dict[str, Any] | None = None,
    momentum: dict[str, Any] | None = None,
    market_alignment: dict[str, Any] | None = None,
) -> StrategyResult:
    """
    Evaluate a signal through the future strategy-engine interface.

    This is intentionally observe-only. It does not replace app.py's current
    risk gates or Claude decision path.
    """
    account_state = account_state or {}
    trend = trend or {}
    momentum = momentum or {}
    market_alignment = market_alignment or {}

    thesis = score_trade(
        symbol=symbol,
        action=action,
        account_state=account_state,
        trend=trend,
        momentum=momentum,
        market_alignment=market_alignment,
    )

    notes = [
        "observe_only=true",
        "current app.py process_signal remains source of live behavior",
        "trader_brain score is informational only",
    ]

    return StrategyResult(
        symbol=symbol.upper(),
        action=action.lower(),
        observe_only=True,
        trader_brain=thesis.to_dict(),
        final_decision=None,
        notes=notes,
    )
