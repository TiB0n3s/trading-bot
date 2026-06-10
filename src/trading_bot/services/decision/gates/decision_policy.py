"""Decision-policy gate trace adapter."""

from typing import Any

from services.decision.gates.base import evidence_gate
from services.decision.trace import GateResult


def build_decision_policy_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="decision_policy",
        layer="policy",
        evidence=account_state.get("decision_policy"),
        default_reason="decision policy evidence not present in account_state",
    )
