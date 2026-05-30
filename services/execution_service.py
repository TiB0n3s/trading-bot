"""Execution stage interfaces for the signal pipeline."""

from __future__ import annotations

from typing import Callable

from services.signal_models import ExecutionResult, SignalContext


class ExecutionService:
    def __init__(self, legacy_processor: Callable[[dict], None]):
        self.legacy_processor = legacy_processor

    def execute_legacy(self, signal: SignalContext) -> ExecutionResult:
        self.legacy_processor(signal.raw_signal)
        return ExecutionResult(submitted=False, status="handled_by_legacy_processor")
