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
from services.signal_models import PipelineResult, SignalContext, SignalRuntimeState


@dataclass(frozen=True)
class SignalPipelineDeps:
    legacy_processor: Callable[..., None]
    build_runtime_state: Callable[[SignalContext], SignalRuntimeState]
    build_context_runtime: Callable[[SignalRuntimeState], Any]
    has_open_position_db: Callable[[str], bool]
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

        with stage_timer("preflight"):
            preflight_handled = self.preflight(context)
        if preflight_handled:
            return PipelineResult(handled=True, context=context)

        with stage_timer("runtime_state"):
            runtime_state = self.deps.build_runtime_state(context)
        with stage_timer("context_runtime"):
            context_runtime = self.deps.build_context_runtime(runtime_state)

        # The real trading decisions are still owned by the legacy processor
        # until those branches are fully extracted. Runtime/context are prepared
        # here to create the next safe ownership seam.
        with stage_timer("legacy_live_execution"):
            execution = self.execution_service.execute_legacy(
                context,
                runtime_state=runtime_state,
                context_runtime=context_runtime,
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

    def preflight(self, context: SignalContext) -> bool:
        if context.action == "sell" and not self.deps.has_open_position_db(context.symbol):
            self.deps.log_rejection(
                context.symbol,
                context.action,
                "ghost_sell",
                "no open Alpaca position",
                price=context.price,
            )
            if context.dedupe_key:
                self.deps.mark_webhook_event_status(
                    context.dedupe_key,
                    "rejected",
                    failure_reason=format_rejection_reason(
                        "ghost_sell",
                        "no open Alpaca position",
                    ),
                )
            return True
        return False
