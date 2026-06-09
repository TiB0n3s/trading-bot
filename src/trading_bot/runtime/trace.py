"""Canonical decision trace contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

GateDecision = Literal["pass", "warn", "cap", "block", "observe"]
GateAuthority = Literal["none", "paper", "live"]


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    layer: str
    decision: GateDecision
    authority: GateAuthority = "none"
    enforced: bool = False
    reason: str = ""
    size_cap_pct: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionTrace:
    trace_version: str = "decision_trace_v1"
    final_decision: str = "pending"
    blocking_gate: str | None = None
    dominant_limiter: str | None = None
    active_caps: list[dict[str, Any]] = field(default_factory=list)
    gate_results: list[GateResult] = field(default_factory=list)
    shadow: dict[str, Any] = field(default_factory=dict)

    def add(self, result: GateResult) -> None:
        self.gate_results.append(result)
        if result.decision == "block" and result.enforced and self.blocking_gate is None:
            self.blocking_gate = result.gate_id
        if result.decision == "cap" and result.enforced:
            self.active_caps.append(
                {
                    "gate_id": result.gate_id,
                    "layer": result.layer,
                    "size_cap_pct": result.size_cap_pct,
                    "reason": result.reason,
                }
            )
            if self.dominant_limiter is None:
                self.dominant_limiter = result.gate_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_version": self.trace_version,
            "final_decision": self.final_decision,
            "blocking_gate": self.blocking_gate,
            "dominant_limiter": self.dominant_limiter,
            "active_caps": list(self.active_caps),
            "gate_results": [row.to_dict() for row in self.gate_results],
            "shadow": dict(self.shadow),
        }


@dataclass(frozen=True)
class DecisionState:
    signal: dict[str, Any]
    market: dict[str, Any] = field(default_factory=dict)
    setup: dict[str, Any] = field(default_factory=dict)
    prediction: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    portfolio: dict[str, Any] = field(default_factory=dict)
    authority: dict[str, Any] = field(default_factory=dict)
    sizing: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)

    def to_legacy_account_state(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "setup_quality": self.setup,
            "prediction_gate": self.prediction,
            "session_momentum_gate": self.session,
            "portfolio_decision": self.portfolio,
            "authority": self.authority,
            "sizing": self.sizing,
            "decision_trace": self.trace,
        }
