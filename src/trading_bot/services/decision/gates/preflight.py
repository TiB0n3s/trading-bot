"""Preflight gate trace adapter."""

from typing import Any

from ..trace import GateResult
from .base import evidence_gate


def build_preflight_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="preflight",
        layer="preflight",
        evidence=account_state.get("preflight"),
        default_reason="preflight evidence not present in account_state",
    )
