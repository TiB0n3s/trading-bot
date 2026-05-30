"""Execution boundary for signal orders.

This module owns the broker-adjacent execution path only: final safety checks,
order submission, broker/null-order normalization, and exception classification.
It intentionally does not write trade rows, rejection rows, snapshots, cooldowns,
or webhook status. Those side effects belong to the audit/persistence boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any, Callable

from services.signal_models import ExecutionResult, SignalContext


@dataclass(frozen=True)
class ExecutionOutcome:
    submitted: bool
    status: str
    order_result: dict[str, Any] | None = None
    rejection_category: str | None = None
    rejection_reason: str | None = None
    failure_reason: str | None = None
    decision_updates: dict[str, Any] = field(default_factory=dict)
    account_state_updates: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def execute_order(
    *,
    symbol: str,
    action: str,
    signal: dict[str, Any],
    signal_price: Any,
    decision: dict[str, Any],
    account_state: dict[str, Any],
    position_size_pct: float,
    execution_mode: str,
    pre_order_safety_check: Callable[..., tuple[bool, str]],
    one_bar_confirmation_hold: Callable[..., tuple[bool, str]],
    make_client_order_id: Callable[[str, str, dict[str, Any]], str],
    place_order: Callable[..., dict[str, Any] | None],
    log: logging.Logger,
) -> ExecutionOutcome:
    """Submit an approved signal order or return a normalized block/failure."""
    log.info(
        f"ORDER PATH START: {symbol} {action.upper()} "
        f"exec_mode={execution_mode} "
        f"position_size_pct={decision.get('position_size_pct')} "
        f"adjusted_position_size_pct={position_size_pct:.3f}"
    )

    if execution_mode == "dry_run":
        log.warning(
            f"DRY RUN: order not submitted for {symbol} {action.upper()} "
            f"position_size_pct={position_size_pct:.3f}"
        )
        order_result = {
            "order_id": f"dry_run_{symbol}_{action}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "symbol": symbol,
            "side": action,
            "qty": 0,
            "stop_loss": None,
            "take_profit": None,
            "status": "dry_run",
        }
        return ExecutionOutcome(
            submitted=False,
            status="dry_run",
            order_result=order_result,
        )

    log.info(f"SECOND LOOK START: {symbol} {action.upper()}")
    ok, second_look_reason = pre_order_safety_check(
        symbol=symbol,
        action=action,
        signal_price=signal_price,
        account_state=account_state,
    )
    log.info(
        f"SECOND LOOK RESULT: {symbol} {action.upper()} "
        f"ok={ok} reason={second_look_reason}"
    )

    if not ok:
        return ExecutionOutcome(
            submitted=False,
            status="rejected",
            rejection_category="second_look",
            rejection_reason=second_look_reason,
            failure_reason=f"second_look: {second_look_reason}",
        )

    account_state_updates: dict[str, Any] = {}
    if action == "buy":
        one_bar_ok, one_bar_reason = one_bar_confirmation_hold(
            symbol=symbol,
            signal_price=signal_price,
            account_state=account_state,
        )
        account_state_updates["one_bar_confirmation_hold"] = {
            "allowed": one_bar_ok,
            "reason": one_bar_reason,
        }

        if not one_bar_ok:
            return ExecutionOutcome(
                submitted=False,
                status="rejected",
                rejection_category="one_bar_confirmation_hold",
                rejection_reason=one_bar_reason,
                failure_reason=f"one_bar_confirmation_hold: {one_bar_reason}",
                account_state_updates=account_state_updates,
            )

        log.info(f"One-bar confirmation hold passed for {symbol} BUY: {one_bar_reason}")

    client_order_id = make_client_order_id(symbol, action, signal)
    log.info(
        f"BROKER SUBMIT START: {symbol} {action.upper()} "
        f"client_order_id={client_order_id}"
    )

    order_result = place_order(
        symbol=symbol,
        action=action,
        position_size_pct=position_size_pct,
        stop_loss_pct=decision.get("stop_loss_pct", 1.75),
        take_profit_pct=0,
        risk_level=account_state.get("risk_level"),
        client_order_id=client_order_id,
    )

    log.info(
        f"BROKER SUBMIT RESULT: {symbol} {action.upper()} "
        f"order_result={order_result}"
    )

    if not order_result:
        return ExecutionOutcome(
            submitted=False,
            status="submit_failed",
            order_result=None,
            failure_reason="broker returned no order_result",
            decision_updates={
                "approved": False,
                "reason": "order_submission_failed: broker returned no order_result",
            },
            account_state_updates=account_state_updates,
            metadata={"client_order_id": client_order_id},
        )

    return ExecutionOutcome(
        submitted=True,
        status="submitted",
        order_result=order_result,
        account_state_updates=account_state_updates,
        metadata={"client_order_id": client_order_id},
    )


class ExecutionService:
    def __init__(self, legacy_processor: Callable[[dict], None] | None = None):
        self.legacy_processor = legacy_processor

    def execute_legacy(self, signal: SignalContext, **kwargs) -> ExecutionResult:
        if self.legacy_processor is None:
            raise RuntimeError("legacy_processor is not configured")
        self.legacy_processor(signal.raw_signal, **kwargs)
        return ExecutionResult(submitted=False, status="handled_by_legacy_processor")

    def execute_order(self, **kwargs) -> ExecutionOutcome:
        return execute_order(**kwargs)
