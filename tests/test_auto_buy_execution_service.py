#!/usr/bin/env python3
"""Tests for the auto-buy execution boundary service."""

from __future__ import annotations

from pathlib import Path

from services.auto_buy_execution_service import (
    auto_buy_execution_authority,
    build_auto_buy_execution_request,
    execute_auto_buy_order,
)


class FakeBroker:
    def __init__(self, order=None, failure_reason=None):
        self.order = order
        self.failure_reason = failure_reason
        self.calls = []

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return self.order

    def last_order_failure_reason(self):
        return self.failure_reason


def _approved_trace():
    return {
        "trace_version": "decision_trace_v1",
        "final_decision": "approved",
        "gate_results": [
            {
                "gate_id": "execution_quality",
                "decision": "pass",
                "enforced": False,
            }
        ],
    }


def test_build_auto_buy_execution_request_uses_effective_size_cap():
    request = build_auto_buy_execution_request(
        candidate={
            "symbol": "aapl",
            "effective_size_cap_pct": 0.25,
            "risk_level": "medium",
            "canonical_decision_trace": _approved_trace(),
        },
        default_position_size_pct=0.5,
        stop_loss_pct=1.25,
        take_profit_pct=2.5,
        client_order_id_factory=lambda symbol: f"cid-{symbol}",
    )

    assert request.symbol == "AAPL"
    assert request.position_size_pct == 0.25
    assert request.stop_loss_pct == 1.25
    assert request.take_profit_pct == 2.5
    assert request.risk_level == "medium"
    assert request.client_order_id == "cid-AAPL"
    assert request.decision_trace["final_decision"] == "approved"


def test_execute_auto_buy_order_submits_buy_through_broker_boundary():
    broker = FakeBroker(order={"id": "order-1"})
    request = build_auto_buy_execution_request(
        candidate={
            "symbol": "AAPL",
            "risk_level": "medium",
            "canonical_decision_trace": _approved_trace(),
        },
        default_position_size_pct=0.5,
        stop_loss_pct=1.25,
        take_profit_pct=2.5,
        client_order_id_factory=lambda symbol: f"cid-{symbol}",
    )

    outcome = execute_auto_buy_order(request, broker)

    assert outcome.submitted is True
    assert outcome.order == {"id": "order-1"}
    assert broker.calls == [
        {
            "symbol": "AAPL",
            "action": "buy",
            "position_size_pct": 0.5,
            "stop_loss_pct": 1.25,
            "take_profit_pct": 2.5,
            "risk_level": "medium",
            "client_order_id": "cid-AAPL",
        }
    ]


def test_execute_auto_buy_order_normalizes_broker_failure():
    broker = FakeBroker(order=None, failure_reason="insufficient buying power")
    request = build_auto_buy_execution_request(
        candidate={"symbol": "AAPL", "canonical_decision_trace": _approved_trace()},
        default_position_size_pct=0.5,
        stop_loss_pct=1.25,
        take_profit_pct=2.5,
        client_order_id_factory=lambda symbol: f"cid-{symbol}",
    )

    outcome = execute_auto_buy_order(request, broker)

    assert outcome.submitted is False
    assert outcome.order is None
    assert outcome.failure_reason == "insufficient buying power"
    assert outcome.live_block_reason == "broker returned no order: insufficient buying power"


def test_execute_auto_buy_order_blocks_without_canonical_approval_trace():
    broker = FakeBroker(order={"id": "order-1"})
    request = build_auto_buy_execution_request(
        candidate={"symbol": "AAPL"},
        default_position_size_pct=0.5,
        stop_loss_pct=1.25,
        take_profit_pct=2.5,
        client_order_id_factory=lambda symbol: f"cid-{symbol}",
    )

    outcome = execute_auto_buy_order(request, broker)

    assert outcome.submitted is False
    assert outcome.order is None
    assert outcome.live_block_reason == "missing canonical decision trace"
    assert broker.calls == []


def test_auto_buy_execution_authority_blocks_enforced_trace_blockers():
    allowed, reason = auto_buy_execution_authority(
        {
            "final_decision": "approved",
            "gate_results": [
                {
                    "gate_id": "cash_safe",
                    "decision": "block",
                    "enforced": True,
                }
            ],
        }
    )

    assert allowed is False
    assert "cash_safe" in reason


def test_auto_buy_manager_does_not_directly_submit_broker_orders():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "auto_buy_manager.py").read_text()
    assert ".place_order(" not in source


def main():
    tests = [
        test_build_auto_buy_execution_request_uses_effective_size_cap,
        test_execute_auto_buy_order_submits_buy_through_broker_boundary,
        test_execute_auto_buy_order_normalizes_broker_failure,
        test_execute_auto_buy_order_blocks_without_canonical_approval_trace,
        test_auto_buy_execution_authority_blocks_enforced_trace_blockers,
        test_auto_buy_manager_does_not_directly_submit_broker_orders,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} auto-buy execution service tests passed.")


if __name__ == "__main__":
    main()
