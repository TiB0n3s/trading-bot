"""Sizing gate trace adapter."""

from typing import Any

from services.decision.gates.base import evidence_gate
from services.decision.trace import GateResult


def build_sizing_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="final_sizing",
        layer="sizing",
        evidence=account_state.get("sizing") or account_state.get("conviction_stack"),
        default_reason="final sizing evidence not present in account_state",
    )
