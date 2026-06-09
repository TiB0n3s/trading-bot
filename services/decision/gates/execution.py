"""Execution-quality gate trace adapter."""

from typing import Any

from services.decision.gates.base import evidence_gate
from services.decision.trace import GateResult


def build_execution_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="execution_quality",
        layer="execution",
        evidence=account_state.get("execution_quality"),
        default_reason="execution quality evidence not present in account_state",
    )
