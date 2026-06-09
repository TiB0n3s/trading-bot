"""Preflight gate trace adapter."""

from typing import Any

from services.decision.gates.base import evidence_gate
from services.decision.trace import GateResult


def build_preflight_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="preflight",
        layer="preflight",
        evidence=account_state.get("preflight"),
        default_reason="preflight evidence not present in account_state",
    )
