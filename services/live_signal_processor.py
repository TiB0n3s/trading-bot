"""Service-owned live signal orchestration.

This module is the migration target for the staged legacy signal flow.  The
first pass keeps behavior-compatible helper names while moving ownership out of
the Flask composition root.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from services.signal_models import PipelineResult, SignalContext, SignalRuntimeState


@dataclass(frozen=True)
class LiveSignalProcessorDeps:
    log: Any


class LiveSignalProcessor:
    def __init__(self, deps: LiveSignalProcessorDeps):
        self.deps = deps

    def process(
        self,
        context: SignalContext,
        runtime_state: SignalRuntimeState,
        context_runtime: Any,
        preflight_result: Any | None = None,
    ) -> PipelineResult | None:
        raise NotImplementedError("LiveSignalProcessor wiring is introduced in a later phase")
