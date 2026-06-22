"""Canonical decision orchestration boundary for live signal processing.

The legacy live signal processor still contains detailed compatibility gate
logic. This orchestrator owns the runtime handoff so deployed signal processing
flows through the canonical decision package before any compatibility delegate
can submit or reject an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_bot.services.signal_models import (
    ExecutionResult,
    PipelineResult,
    SignalContext,
    SignalRuntimeState,
)
from trading_bot.signals.live.gate_context import DecisionTrace as OutputTrace

from .engine import DecisionEngine


def _execution_mode(runtime_state: SignalRuntimeState) -> str:
    mode = (
        runtime_state.account_state.get("execution_mode")
        or runtime_state.account_state.get("mode")
        or "paper"
    )
    return str(mode).strip().lower() or "paper"


def _pre_decision(context: SignalContext) -> dict[str, Any]:
    return {
        "approved": False,
        "confidence": "pending",
        "reason": "canonical orchestrator pre-execution trace",
        "position_size_pct": None,
        "symbol": context.symbol,
        "action": context.action,
    }


@dataclass(frozen=True)
class CanonicalDecisionOrchestrator:
    """Own live orchestration while delegating compatibility implementation."""

    compatibility_processor: Any
    decision_engine: DecisionEngine | None = None

    def process(
        self,
        context: SignalContext,
        runtime_state: SignalRuntimeState,
        context_runtime: Any,
        preflight_result: Any | None = None,
    ) -> PipelineResult:
        gate_trace = OutputTrace()
        engine = self.decision_engine or DecisionEngine()
        evaluation = engine.store_to_account_state(
            account_state=runtime_state.account_state,
            decision=_pre_decision(context),
            source="canonical_signal_orchestrator",
            execution_mode=_execution_mode(runtime_state),
            gate_trace=gate_trace,
        )
        runtime_state.decision_context["canonical_orchestrator"] = {
            "status": "pre_trace_recorded",
            "trace_version": evaluation.trace.trace_version,
            "dominant_limiter": evaluation.trace.dominant_limiter,
        }

        result = self.compatibility_processor.process(
            context,
            runtime_state,
            context_runtime,
            preflight_result,
        )
        if result is None:
            result = PipelineResult(
                handled=True,
                context=context,
                execution=ExecutionResult(
                    submitted=False,
                    status="handled_by_canonical_decision_orchestrator",
                ),
            )
        if result.execution is None:
            result.execution = ExecutionResult(
                submitted=False,
                status="handled_by_canonical_decision_orchestrator",
            )
        elif not result.execution.status:
            result.execution.status = "handled_by_canonical_decision_orchestrator"

        _delegate = type(self.compatibility_processor).__name__
        runtime_state.account_state["canonical_orchestration_status"] = "handled"
        runtime_state.account_state["canonical_orchestration_delegate"] = _delegate
        gate_trace.record("canonical_orchestration_status", "handled")
        gate_trace.record("canonical_orchestration_delegate", _delegate)
        return result
