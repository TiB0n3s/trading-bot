"""Trend-confirmation gate trace adapter."""

from typing import Any

from services.decision.gates.base import evidence_gate
from services.decision.trace import GateResult


def build_trend_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="trend_confirmation",
        layer="trend",
        evidence=account_state.get("trend_confirmation") or account_state.get("trend_gate"),
        default_reason="trend confirmation evidence not present in account_state",
    )
