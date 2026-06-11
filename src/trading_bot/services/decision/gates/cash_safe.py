"""Cash-safe gate trace adapter."""

from typing import Any

from ..trace import GateResult
from .base import evidence_gate


def build_cash_safe_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="cash_safe",
        layer="risk",
        evidence=account_state.get("cash_safe") or account_state.get("cash_safe_gate"),
        default_reason="cash-safe evidence not present in account_state",
    )
