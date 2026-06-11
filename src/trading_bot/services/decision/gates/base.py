"""Helpers for trace-native decision gates."""

from __future__ import annotations

from typing import Any

from ..trace import GateResult


def evidence_gate(
    *,
    gate_id: str,
    layer: str,
    evidence: dict[str, Any] | None,
    default_reason: str,
    enforced: bool = False,
) -> GateResult:
    evidence = evidence if isinstance(evidence, dict) else {}
    raw_decision = str(
        evidence.get("decision")
        or evidence.get("severity")
        or evidence.get("status")
        or evidence.get("result")
        or ""
    ).lower()
    if raw_decision in {"block", "blocked", "hard_block", "reject", "rejected"}:
        decision = "block"
    elif raw_decision in {"size_down", "reduce", "cap"}:
        decision = "cap"
    elif raw_decision in {"warn", "warning", "caution"}:
        decision = "warn"
    elif raw_decision in {"pass", "allow", "approved", "ok"}:
        decision = "pass"
    else:
        decision = "observe"
    return GateResult(
        gate_id=gate_id,
        layer=layer,
        decision=decision,
        authority="none",
        enforced=enforced,
        reason=str(evidence.get("reason") or evidence.get("summary") or default_reason),
        size_cap_pct=evidence.get("size_cap_pct") or evidence.get("max_size_pct"),
        inputs=evidence,
        outputs={"trace_source": "account_state"},
    )
