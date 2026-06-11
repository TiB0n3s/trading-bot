"""Sizing gate trace adapter."""

from typing import Any

from ..trace import GateResult
from .base import evidence_gate


def build_sizing_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="final_sizing",
        layer="sizing",
        evidence=account_state.get("sizing") or account_state.get("conviction_stack"),
        default_reason="final sizing evidence not present in account_state",
    )
