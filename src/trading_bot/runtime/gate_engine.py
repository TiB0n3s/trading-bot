"""Small first-class gate engine used by runtime approval paths."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from trading_bot.runtime.trace import DecisionTrace, GateResult


class Gate(Protocol):
    gate_id: str
    layer: str

    def evaluate(self, state: dict[str, Any]) -> GateResult: ...


@dataclass(frozen=True)
class CallableGate:
    gate_id: str
    layer: str
    fn: Any

    def evaluate(self, state: dict[str, Any]) -> GateResult:
        started = perf_counter()
        result = self.fn(state)
        elapsed_ms = (perf_counter() - started) * 1000.0
        if isinstance(result, GateResult):
            return GateResult(
                **{
                    **result.to_dict(),
                    "elapsed_ms": round(elapsed_ms, 3),
                }
            )
        raise TypeError(f"{self.gate_id} returned unsupported gate result")


class GateEngine:
    def __init__(self, gates: list[Gate]):
        self.gates = list(gates)

    def run(self, state: dict[str, Any]) -> DecisionTrace:
        trace = DecisionTrace()
        for gate in self.gates:
            result = gate.evaluate(state)
            trace.add(result)
            if result.decision == "block" and result.enforced:
                break
        final = state.get("final_decision")
        if trace.blocking_gate:
            trace.final_decision = "rejected"
        elif final:
            trace.final_decision = str(final)
        else:
            trace.final_decision = "approved"
        return trace
