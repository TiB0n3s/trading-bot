"""Prediction gate trace adapter."""

from typing import Any

from services.decision.gates.base import evidence_gate
from services.decision.trace import GateResult


def build_prediction_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="prediction",
        layer="prediction",
        evidence=account_state.get("prediction_gate"),
        default_reason="prediction evidence not present in account_state",
    )
