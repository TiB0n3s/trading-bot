"""Macro gate trace adapter."""

from typing import Any

from ..trace import GateResult
from .base import evidence_gate


def build_macro_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="macro",
        layer="macro",
        evidence=account_state.get("macro_risk") or account_state.get("macro_gate"),
        default_reason="macro evidence not present in account_state",
    )
