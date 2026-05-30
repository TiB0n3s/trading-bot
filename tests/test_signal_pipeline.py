#!/usr/bin/env python3
"""Unit tests for the deterministic signal pipeline seam."""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.signal_pipeline import SignalPipeline, SignalPipelineDeps
from services.observability import metrics_snapshot, reset_metrics
from services.preflight_service import PreflightResult
from services.signal_models import SignalRuntimeState


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy, got {value!r}")


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.infos = []
        self.errors = []

    def warning(self, message):
        self.warnings.append(message)

    def info(self, message):
        self.infos.append(message)

    def error(self, message):
        self.errors.append(message)


class Recorder:
    def __init__(self):
        self.calls = []

    def process(self, context, runtime_state, context_runtime, preflight_result):
        self.calls.append(
            (
                "live_signal",
                dict(context.raw_signal),
                {
                    "runtime_state": runtime_state,
                    "context_runtime": context_runtime,
                    "preflight_result": preflight_result,
                },
            )
        )
        from services.signal_models import ExecutionResult, PipelineResult
        return PipelineResult(
            handled=True,
            context=context,
            execution=ExecutionResult(
                submitted=False,
                status="handled_by_live_signal_processor",
            ),
        )

    def build_runtime_state(self, context):
        self.calls.append(("build_runtime_state", context.symbol, context.action))
        return SignalRuntimeState(
            raw_signal=context.raw_signal,
            symbol=context.symbol,
            action=context.action,
            received_at=datetime.now(),
            account_state={"test": True},
        )

    def build_context_runtime(self, runtime_state):
        self.calls.append(("build_context_runtime", runtime_state.symbol, runtime_state.action))
        return {"context_runtime": runtime_state.symbol}

    def evaluate_preflight(self, runtime_state):
        self.calls.append(("evaluate_preflight", runtime_state.symbol, runtime_state.action))
        if runtime_state.symbol == "MSFT" and runtime_state.action == "sell":
            return PreflightResult(
                allowed=False,
                rejection_category="ghost_sell",
                rejection_reason="no open Alpaca position",
            )
        return PreflightResult(
            allowed=True,
            metadata={"existing_position": {"symbol": runtime_state.symbol}},
        )

    def log_rejection(self, *args, **kwargs):
        self.calls.append(("log_rejection", args, kwargs))

    def mark_webhook_event_status(self, *args, **kwargs):
        self.calls.append(("mark_webhook_event_status", args, kwargs))


def _pipeline(recorder=None, logger=None):
    recorder = recorder or Recorder()
    logger = logger or FakeLogger()
    return SignalPipeline(
        SignalPipelineDeps(
            live_signal_processor=recorder,
            build_runtime_state=recorder.build_runtime_state,
            build_context_runtime=recorder.build_context_runtime,
            evaluate_preflight=recorder.evaluate_preflight,
            log_rejection=recorder.log_rejection,
            mark_webhook_event_status=recorder.mark_webhook_event_status,
            logger=logger,
        )
    ), recorder, logger


def test_normalize_preserves_original_and_returns_typed_context():
    pipeline, _, _ = _pipeline()
    raw = {"action": " BUY ", "symbol": " aapl ", "price": "199.25", "_dedupe_key": "abc"}

    context = pipeline.normalize(raw)

    assert_equal(raw["action"], " BUY ", "raw action should not be mutated")
    assert_equal(context.action, "buy", "normalized action")
    assert_equal(context.symbol, "AAPL", "normalized symbol")
    assert_equal(context.price, 199.25, "normalized price")
    assert_equal(context.dedupe_key, "abc", "dedupe key")
    assert_equal(context.raw_signal["action"], "buy", "legacy payload action")


def test_invalid_payload_is_rejected_before_live_signal_processor():
    pipeline, recorder, logger = _pipeline()

    result = pipeline.run({"action": "hold", "symbol": "AAPL", "price": 199, "_dedupe_key": "abc"})

    assert_true(result.error is not None, "validation error captured")
    assert_true(logger.warnings, "validation warning logged")
    assert_equal([call[0] for call in recorder.calls], ["mark_webhook_event_status"], "call order")
    assert_equal(recorder.calls[0][1][0], "abc", "dedupe key marked")
    assert_equal(recorder.calls[0][1][1], "rejected", "dedupe status")


def test_ghost_sell_is_rejected_before_live_signal_processor():
    pipeline, recorder, _ = _pipeline()

    result = pipeline.run({"action": "sell", "symbol": "MSFT", "price": 405, "_dedupe_key": "sell-1"})

    assert_true(result.context is not None, "context returned")
    assert_equal(
        [call[0] for call in recorder.calls],
        [
            "build_runtime_state",
            "build_context_runtime",
            "evaluate_preflight",
            "log_rejection",
            "mark_webhook_event_status",
        ],
        "call order",
    )
    assert_equal(recorder.calls[3][1][:4], ("MSFT", "sell", "ghost_sell", "no open Alpaca position"), "rejection")
    assert_equal(recorder.calls[4][1][1], "rejected", "dedupe status")


def test_valid_signal_runs_live_signal_orchestration_stage_once():
    reset_metrics()
    pipeline, recorder, _ = _pipeline()

    result = pipeline.run({"action": "buy", "symbol": "aapl", "price": "199.25"})

    assert_true(result.execution is not None, "execution result")
    assert_equal(result.execution.status, "handled_by_live_signal_processor", "execution status")
    assert_equal(
        [call[0] for call in recorder.calls],
        ["build_runtime_state", "build_context_runtime", "evaluate_preflight", "live_signal"],
        "call order",
    )
    assert_equal(recorder.calls[3][1]["symbol"], "AAPL", "live symbol normalized")
    assert_true("runtime_state" in recorder.calls[3][2], "runtime state passed to live processor")
    assert_true("context_runtime" in recorder.calls[3][2], "context runtime passed to live processor")
    assert_true("preflight_result" in recorder.calls[3][2], "preflight result passed to live processor")
    timing = metrics_snapshot()["pipeline_stage_timing"]
    for stage in ("normalize", "preflight", "runtime_state", "context_runtime", "live_signal_orchestration"):
        assert_true(stage in timing, f"{stage} timing recorded")
    for placeholder_stage in ("context_build", "approval", "sizing", "execution"):
        assert_true(
            placeholder_stage not in timing,
            f"{placeholder_stage} placeholder timing should not be recorded",
        )


def main():
    tests = [
        test_normalize_preserves_original_and_returns_typed_context,
        test_invalid_payload_is_rejected_before_live_signal_processor,
        test_ghost_sell_is_rejected_before_live_signal_processor,
        test_valid_signal_runs_live_signal_orchestration_stage_once,
    ]
    for test in tests:
        test()
    print(f"[OK] {len(tests)} signal pipeline tests passed")


if __name__ == "__main__":
    main()
