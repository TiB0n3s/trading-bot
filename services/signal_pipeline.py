"""Deterministic signal pipeline orchestration.

The live trading context is still assembled by the legacy processor during the
current migration. This pipeline owns only the real outer stages today:
normalization, preflight, and delegation to the legacy live signal path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from exceptions import ValidationError
from rejection_categories import format_rejection_reason
from services.execution_service import ExecutionService
from services.observability import stage_timer
from services.preflight_service import PreflightResult
from services.signal_models import PipelineResult, SignalContext, SignalRuntimeState


@dataclass(frozen=True)
class SignalPipelineDeps:
    legacy_processor: Callable[..., None]
    build_runtime_state: Callable[[SignalContext], SignalRuntimeState]
    build_context_runtime: Callable[[SignalRuntimeState], Any]
    evaluate_preflight: Callable[[SignalRuntimeState], PreflightResult]
    log_rejection: Callable[..., None]
    mark_webhook_event_status: Callable[..., None]
    logger: object


class SignalPipeline:
    def __init__(
        self,
        deps: SignalPipelineDeps,
        execution_service: ExecutionService | None = None,
    ):
        self.deps = deps
        self.execution_service = execution_service or ExecutionService(deps.legacy_processor)

    def run(self, raw_signal: dict) -> PipelineResult:
        try:
            with stage_timer("normalize"):
                context = self.normalize(raw_signal)
        except ValidationError as exc:
            self.deps.logger.warning(f"Invalid signal payload rejected: {exc}")
            dedupe_key = raw_signal.get("_dedupe_key")
            if dedupe_key:
                self.deps.mark_webhook_event_status(
                    dedupe_key,
                    "rejected",
                    failure_reason=format_rejection_reason(
                        "payload_validation",
                        str(exc),
                    ),
                )
            return PipelineResult(handled=True, error=exc)

        with stage_timer("runtime_state"):
            runtime_state = self.deps.build_runtime_state(context)
        with stage_timer("context_runtime"):
            context_runtime = self.deps.build_context_runtime(runtime_state)
        with stage_timer("preflight"):
            preflight_result = self.deps.evaluate_preflight(runtime_state)
        if not preflight_result.allowed:
            category = preflight_result.rejection_category or "preflight"
            reason = preflight_result.rejection_reason or "preflight rejected signal"
            level = preflight_result.metadata.get("log_level", "warning")
            message = f"{category} blocked {context.symbol} {context.action.upper()}: {reason}"
            if level == "info":
                self.deps.logger.info(message)
            elif level == "error":
                self.deps.logger.error(message)
            else:
                self.deps.logger.warning(message)
            self.deps.log_rejection(
                context.symbol,
                context.action,
                category,
                reason,
                price=context.price,
                account_state=runtime_state.account_state,
            )
            if context.dedupe_key:
                self.deps.mark_webhook_event_status(
                    context.dedupe_key,
                    "rejected",
                    failure_reason=format_rejection_reason(category, reason),
                )
            return PipelineResult(handled=True, context=context)

        # The real trading decisions are still owned by the legacy processor
        # until those branches are fully extracted. Runtime/context are prepared
        # here to create the next safe ownership seam.
        with stage_timer("legacy_live_execution"):
            execution = self.execution_service.execute_legacy(
                context,
                runtime_state=runtime_state,
                context_runtime=context_runtime,
                preflight_result=preflight_result,
            )
        self.deps.logger.info(
            "signal_pipeline_decision "
            f"symbol={context.symbol} action={context.action} "
            f"execution_status={execution.status}"
        )
        return PipelineResult(
            handled=True,
            context=context,
            execution=execution,
        )

    def normalize(self, raw_signal: dict) -> SignalContext:
        dedupe_key = raw_signal.get("_dedupe_key")
        try:
            action = str(raw_signal.get("action", "")).strip().lower()
            symbol = str(raw_signal.get("symbol", "")).strip().upper()
            price = float(raw_signal.get("price", 0))
            if action not in ("buy", "sell"):
                raise ValidationError(f"invalid action={action!r}")
            if not symbol:
                raise ValidationError("missing symbol")
        except (TypeError, ValueError, ValidationError) as exc:
            raise ValidationError(str(exc)) from exc

        normalized_signal = dict(raw_signal)
        normalized_signal["action"] = action
        normalized_signal["symbol"] = symbol
        normalized_signal["price"] = price
        return SignalContext(
            raw_signal=normalized_signal,
            dedupe_key=dedupe_key,
            action=action,
            symbol=symbol,
            price=price,
        )
