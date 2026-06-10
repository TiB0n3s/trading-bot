"""Session-momentum gate trace adapter."""

from typing import Any

from services.decision.gates.base import evidence_gate
from services.decision.trace import GateResult


def build_session_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="session_momentum",
        layer="session",
        evidence=account_state.get("session_momentum_gate")
        or account_state.get("session_momentum"),
        default_reason="session momentum evidence not present in account_state",
    )
