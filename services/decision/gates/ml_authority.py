"""ML authority gate trace adapter."""

from typing import Any

from services.decision.gates.base import evidence_gate
from services.decision.trace import GateResult


def build_ml_authority_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="ml_authority",
        layer="ml",
        evidence=account_state.get("ml_authority") or account_state.get("ml_authority_gate"),
        default_reason="ML authority evidence not present in account_state",
    )
