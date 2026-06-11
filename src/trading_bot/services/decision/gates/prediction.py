"""Prediction gate trace adapter."""

from typing import Any

from ..trace import GateResult
from .base import evidence_gate


def build_prediction_gate(account_state: dict[str, Any]) -> GateResult:
    return evidence_gate(
        gate_id="prediction",
        layer="prediction",
        evidence=account_state.get("prediction_gate"),
        default_reason="prediction evidence not present in account_state",
    )
