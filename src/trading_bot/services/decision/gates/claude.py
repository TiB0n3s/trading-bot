"""Claude approval gate trace adapter."""

from typing import Any

from ..trace import GateResult


def build_claude_gate(
    *,
    decision: dict[str, Any],
    source: str,
    authority: str,
) -> GateResult:
    approved = bool(decision.get("approved"))
    return GateResult(
        gate_id="claude_approval",
        layer="approval",
        decision="pass" if approved else "block",
        authority=authority,
        enforced=source == "claude",
        reason=str(decision.get("reason") or ""),
        inputs={"confidence": decision.get("confidence"), "source": source},
        outputs={"approved": approved},
    )
