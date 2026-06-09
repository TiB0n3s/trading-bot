#!/usr/bin/env python3
"""Tests for enforced broker-adjacent live-risk gates."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.decision.gates.live_risk import (  # noqa: E402
    evaluate_execution_quality_live_gate,
    evaluate_live_circuit_breaker,
)


def test_live_circuit_breaker_blocks_buy_on_max_drawdown():
    gate = evaluate_live_circuit_breaker(
        action="buy",
        account_state={"max_drawdown_pct": 3.25},
        max_drawdown_pct=3.0,
    )

    assert gate.decision == "block"
    assert gate.enforced is True
    assert gate.gate_id == "live_circuit_breaker"
    assert "max_drawdown_pct" in gate.reason


def test_live_circuit_breaker_allows_sells_during_drawdown():
    gate = evaluate_live_circuit_breaker(
        action="sell",
        account_state={"max_drawdown_pct": 10.0, "daily_pnl_pct": -8.0},
        max_drawdown_pct=3.0,
    )

    assert gate.decision == "pass"
    assert gate.enforced is True


def test_execution_quality_block_is_enforced_for_buys():
    gate = evaluate_execution_quality_live_gate(
        action="buy",
        account_state={"execution_quality": {"decision": "block", "reason": "toxic flow"}},
    )

    assert gate.decision == "block"
    assert gate.enforced is True
    assert gate.reason == "toxic flow"


if __name__ == "__main__":
    test_live_circuit_breaker_blocks_buy_on_max_drawdown()
    print("[OK] test_live_circuit_breaker_blocks_buy_on_max_drawdown")
    test_live_circuit_breaker_allows_sells_during_drawdown()
    print("[OK] test_live_circuit_breaker_allows_sells_during_drawdown")
    test_execution_quality_block_is_enforced_for_buys()
    print("[OK] test_execution_quality_block_is_enforced_for_buys")
