"""Execution-quality gate trace adapter."""

from typing import Any

from ..trace import GateResult
from .base import evidence_gate


def build_execution_gate(account_state: dict[str, Any]) -> GateResult:
    execution_quality = account_state.get("execution_quality")
    execution_quality = execution_quality if isinstance(execution_quality, dict) else {}
    return evidence_gate(
        gate_id="execution_quality",
        layer="execution",
        evidence=execution_quality,
        default_reason="execution quality evidence not present in account_state",
        enforced=str(execution_quality.get("decision") or "").strip().lower() == "block",
    )
