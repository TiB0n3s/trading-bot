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
    def execute_order(self, **kwargs) -> ExecutionOutcome:
        return execute_order(**kwargs)


def run_legacy_approved_order_path(
    *,
    signal: dict[str, Any],
    symbol: str,
    action: str,
    price: Any,
    account_state: dict[str, Any],
    dedupe_key: str | None,
    current_et: Any,
    decision: dict[str, Any],
    execution_mode: str,
    apply_final_sizing: Callable[..., Any],
    apply_buy_opportunity_sizing: Callable[..., Any],
    execute_order_func: Callable[..., ExecutionOutcome],
    pre_order_safety_check: Callable[..., tuple[bool, str]],
    one_bar_confirmation_hold: Callable[..., tuple[bool, str]],
    make_client_order_id: Callable[[str, str, dict[str, Any]], str],
    place_order: Callable[..., dict[str, Any] | None],
    execution_rejection_decision: Callable[[ExecutionOutcome], Any],
    deterministic_rejection: Callable[..., Any],
    reject_approval_decision: Callable[..., Any],
    log_trade: Callable[..., Any],
    record_webhook_status: Callable[..., Any],
    write_cooldown: Callable[[str, str, Any], Any],
    write_recent_sell: Callable[[str, Any, Any], Any],
    last_order: dict,
    last_sell: dict,
    log: logging.Logger,
) -> bool:
    """Run the legacy approved/rejected post-Claude order path.

    Returns True when the path rejected and the caller should stop.
    """
    order_result = None

    if decision.get("approved"):
        try:
            approved_reason = decision.get("reason")
            log.info(f"APPROVED: {symbol} {action.upper()} - {approved_reason}")

            risk_multiplier = float(account_state.get("macro_risk", {}).get("risk_multiplier", 1.0))
            sizing_decision = apply_final_sizing(
                symbol=symbol,
                action=action,
                decision=decision,
                risk_multiplier=risk_multiplier,
                account_state=account_state,
                apply_buy_opportunity_sizing=apply_buy_opportunity_sizing,
                log=log,
            )
            adjusted_position_size_pct = sizing_decision.final_size_pct
            account_state["final_sizing"] = {
                "requested_size_pct": sizing_decision.requested_size_pct,
                "final_size_pct": sizing_decision.final_size_pct,
                "dominant_limiter": sizing_decision.dominant_limiter,
                "active_caps": [
                    {"source": cap.source, "cap_pct": cap.cap_pct, "reason": cap.reason}
                    for cap in sizing_decision.active_caps
                ],
                "conviction_stack": sizing_decision.conviction_stack,
            }

            execution = execute_order_func(
                symbol=symbol,
                action=action,
                signal=signal,
                signal_price=price,
                decision=decision,
                account_state=account_state,
                position_size_pct=adjusted_position_size_pct,
                execution_mode=execution_mode,
                pre_order_safety_check=pre_order_safety_check,
                one_bar_confirmation_hold=one_bar_confirmation_hold,
                make_client_order_id=make_client_order_id,
                place_order=place_order,
                log=log,
            )
            account_state.update(execution.account_state_updates)
            if execution.decision_updates:
                decision.update(execution.decision_updates)
            order_result = execution.order_result

            if execution.rejection_category:
                reject_approval_decision(approval=execution_rejection_decision(execution))
                return True

            if order_result:
                if execution_mode == "dry_run":
                    log.info(f"DRY RUN ORDER RECORDED: {order_result}")
                else:
                    log.info(f"ORDER PLACED: {order_result}")
                    cooldown_key = (symbol, action)
                    last_order[cooldown_key] = current_et
                    write_cooldown(symbol, action, current_et)
                    if action == "sell":
                        last_sell[symbol] = (current_et, price)
                        write_recent_sell(symbol, current_et, price)
            else:
                log.error(f"Order placement failed for {symbol}")
                if dedupe_key:
                    record_webhook_status(
                        dedupe_key=dedupe_key,
                        status="submit_failed",
                        failure_reason=execution.failure_reason or "broker returned no order_result",
                    )

        except Exception as exc:
            log.exception(
                f"APPROVED ORDER PATH CRASHED for {symbol} {action.upper()}: {exc}"
            )
            reject_approval_decision(
                approval=deterministic_rejection(
                    category="order_path_exception",
                    reason=str(exc),
                    source="execution",
                ),
                level="error",
            )
            if dedupe_key:
                record_webhook_status(
                    dedupe_key=dedupe_key,
                    status="error",
                    failure_reason=f"order_path_exception: {exc}",
                )
            return True

    else:
        rejected_reason = decision.get("reason")
        log.info(f"REJECTED: {symbol} {action.upper()} - {rejected_reason}")

    log_trade(signal, decision, order_result, account_state=account_state)
    if dedupe_key:
        record_webhook_status(
            dedupe_key=dedupe_key,
            status="processed",
        )

    return False
