"""Execution boundary for auto-buy candidate orders.

Auto-buy still owns candidate discovery and legacy eligibility checks. This
service owns the broker-adjacent submit step so the script no longer calls the
broker directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


class AutoBuyBroker(Protocol):
    def place_order(
        self,
        *,
        symbol: str,
        action: str,
        position_size_pct: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        risk_level: str | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    def last_order_failure_reason(self) -> str | None: ...


@dataclass(frozen=True)
class AutoBuyExecutionRequest:
    symbol: str
    position_size_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    risk_level: str | None
    client_order_id: str
    decision_trace: dict[str, Any] | None = None


@dataclass(frozen=True)
class AutoBuyExecutionOutcome:
    submitted: bool
    order: dict[str, Any] | None
    failure_reason: str | None = None
    live_block_reason: str | None = None


def build_auto_buy_execution_request(
    *,
    candidate: dict[str, Any],
    default_position_size_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    client_order_id_factory: Callable[[str], str],
) -> AutoBuyExecutionRequest:
    symbol = str(candidate["symbol"]).strip().upper()
    return AutoBuyExecutionRequest(
        symbol=symbol,
        position_size_pct=float(
            candidate.get("effective_size_cap_pct") or default_position_size_pct
        ),
        stop_loss_pct=float(stop_loss_pct),
        take_profit_pct=float(take_profit_pct),
        risk_level=candidate.get("risk_level"),
        client_order_id=client_order_id_factory(symbol),
        decision_trace=candidate.get("canonical_decision_trace") or candidate.get("decision_trace"),
    )


def auto_buy_execution_authority(trace: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(trace, dict):
        return False, "missing canonical decision trace"

    final_decision = str(trace.get("final_decision") or "").lower()
    if final_decision != "approved":
        return False, f"canonical decision trace final_decision={final_decision or 'unknown'}"

    blockers = []
    for gate in trace.get("gate_results") or []:
        if not isinstance(gate, dict):
            continue
        decision = str(gate.get("decision") or "").lower()
        enforced = bool(gate.get("enforced"))
        if enforced and decision == "block":
            blockers.append(str(gate.get("gate_id") or "unknown_gate"))
    if blockers:
        return False, "canonical decision trace enforced blockers: " + ", ".join(blockers)

    return True, "canonical decision trace approved execution"


def execute_auto_buy_order(
    request: AutoBuyExecutionRequest,
    broker: AutoBuyBroker,
) -> AutoBuyExecutionOutcome:
    authority_ok, authority_reason = auto_buy_execution_authority(request.decision_trace)
    if not authority_ok:
        return AutoBuyExecutionOutcome(
            submitted=False,
            order=None,
            failure_reason=None,
            live_block_reason=authority_reason,
        )

    order = broker.place_order(
        symbol=request.symbol,
        action="buy",
        position_size_pct=request.position_size_pct,
        stop_loss_pct=request.stop_loss_pct,
        take_profit_pct=request.take_profit_pct,
        risk_level=request.risk_level,
        client_order_id=request.client_order_id,
    )
    if order:
        return AutoBuyExecutionOutcome(submitted=True, order=order)

    failure_reason = broker.last_order_failure_reason()
    return AutoBuyExecutionOutcome(
        submitted=False,
        order=None,
        failure_reason=failure_reason,
        live_block_reason="broker returned no order"
        + (f": {failure_reason}" if failure_reason else ": unknown"),
    )


class AutoBuyExecutionService:
    def __init__(self, broker: AutoBuyBroker):
        self.broker = broker

    def execute(self, request: AutoBuyExecutionRequest) -> AutoBuyExecutionOutcome:
        return execute_auto_buy_order(request, self.broker)
