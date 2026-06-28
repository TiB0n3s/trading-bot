"""Behavior-preserving signal stage guard helpers.

These helpers are migration seams for draining app.py. They decide whether a
stage should continue or return a normalized rejection, but they do not write
audit rows, update signal lifecycle status, or submit orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from services.approval_service import ApprovalDecision, deterministic_rejection
from services.decision.gates.signal_safety import (
    evaluate_cash_safe_gate,
    evaluate_stale_signal_gate,
    evaluate_symbol_override_gate,
)
from services.decision.trace import GateResult


@dataclass(frozen=True)
class SignalStageDecision:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    account_state_updates: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


SIGNAL_STAGE_CONTINUE = SignalStageDecision()


def _decision_from_gate(gate: GateResult) -> SignalStageDecision:
    if gate.decision != "block":
        return SignalStageDecision(
            account_state_updates=gate.outputs.get("account_state_updates") or {},
            metadata=gate.outputs.get("metadata") or {},
        )

    category = gate.outputs.get("rejection_category") or gate.gate_id
    metadata = gate.outputs.get("metadata") or {}
    return SignalStageDecision(
        rejected=True,
        approval=deterministic_rejection(
            category=category,
            reason=gate.reason,
            metadata=metadata or None,
        ),
        metadata=metadata,
    )


def check_stale_signal(
    *,
    raw_signal: dict[str, Any],
    parse_stale_signal: Callable[[dict[str, Any]], tuple[bool, float | None, str]],
) -> SignalStageDecision:
    return _decision_from_gate(
        evaluate_stale_signal_gate(
            raw_signal=raw_signal,
            parse_stale_signal=parse_stale_signal,
        )
    )


def check_cash_safe_gates(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any],
    cash_safe_mode: bool,
    cash_safe_symbols: set[str],
    max_open_positions: int,
    max_new_buys_per_symbol_per_day: int,
    cash_safe_buys_today: Callable[[str], int],
    log: Any = None,
) -> SignalStageDecision:
    return _decision_from_gate(
        evaluate_cash_safe_gate(
            symbol=symbol,
            action=action,
            account_state=account_state,
            cash_safe_mode=cash_safe_mode,
            cash_safe_symbols=cash_safe_symbols,
            max_open_positions=max_open_positions,
            max_new_buys_per_symbol_per_day=max_new_buys_per_symbol_per_day,
            cash_safe_buys_today=cash_safe_buys_today,
            log=log,
        )
    )


def apply_symbol_overrides(
    *,
    symbol: str,
    action: str,
    symbol_override_block: Callable[[str, str], str | None],
) -> SignalStageDecision:
    return _decision_from_gate(
        evaluate_symbol_override_gate(
            symbol=symbol,
            action=action,
            symbol_override_block=symbol_override_block,
        )
    )
