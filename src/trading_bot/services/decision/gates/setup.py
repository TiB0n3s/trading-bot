"""Setup policy gate trace adapter."""

from typing import Any

from ..trace import GateResult
from .base import evidence_gate


def build_setup_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="setup_policy",
        layer="setup",
        evidence=account_state.get("setup_quality") or account_state.get("setup_policy"),
        default_reason="setup policy evidence not present in account_state",
    )
