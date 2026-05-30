"""Deterministic signal pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from exceptions import ValidationError
from rejection_categories import format_rejection_reason
from services.approval_service import ApprovalService
from services.context_builder import ContextBuilder
from services.execution_service import ExecutionService
from services.observability import stage_timer
from services.signal_models import PipelineResult, SignalContext
from services.sizing_service import SizingService


@dataclass(frozen=True)
class SignalPipelineDeps:
    legacy_processor: Callable[[dict], None]
    has_open_position_db: Callable[[str], bool]
    log_rejection: Callable[..., None]
    mark_webhook_event_status: Callable[..., None]
    logger: object


class SignalPipeline:
    def __init__(
        self,
        deps: SignalPipelineDeps,
        context_builder: ContextBuilder | None = None,
        approval_service: ApprovalService | None = None,
        sizing_service: SizingService | None = None,
        execution_service: ExecutionService | None = None,
    ):
        self.deps = deps
        self.context_builder = context_builder or ContextBuilder()
        self.approval_service = approval_service or ApprovalService()
        self.sizing_service = sizing_service or SizingService()
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

        with stage_timer("context_build"):
            decision_context = self.context_builder.build(context)
        with stage_timer("approval"):
            approval = self.approval_service.evaluate(decision_context)
        with stage_timer("sizing"):
            sizing = self.sizing_service.size(approval)
        with stage_timer("execution"):
            execution = self.execution_service.execute_legacy(context)
        self.deps.logger.info(
            "signal_pipeline_decision "
            f"symbol={context.symbol} action={context.action} "
            f"approval={approval.approved} approval_reason={approval.reason} "
            f"sizing_pct={sizing.position_size_pct} execution_status={execution.status}"
        )
        return PipelineResult(
            handled=True,
            context=context,
            approval=approval,
            sizing=sizing,
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
