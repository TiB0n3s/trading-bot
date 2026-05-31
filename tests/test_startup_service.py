#!/usr/bin/env python3
"""Tests for startup orchestration service boundaries."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.startup_service import StartupDeps, StartupService


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy")


class _Position:
    def __init__(self, symbol):
        self.symbol = symbol


def _deps(**overrides):
    calls = []

    def step(name):
        def _inner(*_args, **_kwargs):
            calls.append(name)
        return _inner

    logger = SimpleNamespace(
        info=MagicMock(),
        warning=MagicMock(),
        error=MagicMock(),
    )
    container = SimpleNamespace(
        broker_service=SimpleNamespace(list_positions=MagicMock(return_value=[])),
        repositories=SimpleNamespace(
            context=SimpleNamespace(startup_db_open_symbols=MagicMock(return_value=[]))
        ),
    )
    base = {
        "container": container,
        "logger": logger,
        "init_core_tables": step("core"),
        "ensure_recent_favorable_setups_table": step("recent-table"),
        "prune_recent_favorable_setups": step("recent-prune"),
        "recent_favorable_setup_ttl_minutes": 15,
        "init_session_momentum_table": step("session"),
        "init_db_performance_indexes": step("indexes"),
        "start_prediction_cache_loader": step("prediction-cache"),
        "prediction_cache_status": MagicMock(return_value={"running": True}),
        "get_signal_executor": step("executor"),
        "load_symbol_overrides": step("symbol-overrides"),
        "build_trend_table": step("trend"),
        "hydrate_cooldowns": step("cooldowns"),
        "hydrate_recent_sells": step("recent-sells"),
        "load_market_context": step("market-context"),
        "env_get": lambda _key: "set",
        "ml_authority_config": MagicMock(return_value={"authority_mode": "observe_only_compare"}),
    }
    base.update(overrides)
    return StartupDeps(**base), calls, logger


def test_startup_service_runs_all_steps_even_when_one_fails():
    def broken():
        raise RuntimeError("boom")

    deps, calls, logger = _deps(init_db_performance_indexes=broken)
    StartupService(deps).run()

    assert_true("core" in calls, "early step ran")
    assert_true("market-context" in calls, "later step ran after failure")
    assert_true(logger.error.called, "failure logged")
    assert_true(logger.info.called, "startup info logged")
    assert_true(
        any(
            "ML authority config at startup" in str(call.args[0])
            for call in logger.info.call_args_list
        ),
        "ML authority config logged",
    )


def test_startup_reconcile_reports_position_mismatches():
    container = SimpleNamespace(
        broker_service=SimpleNamespace(
            list_positions=MagicMock(return_value=[_Position("AAPL")])
        ),
        repositories=SimpleNamespace(
            context=SimpleNamespace(
                startup_db_open_symbols=MagicMock(return_value=[{"symbol": "MSFT"}])
            )
        ),
    )
    deps, _calls, logger = _deps(container=container)

    StartupService(deps).reconcile_positions()

    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert_true(any("AAPL held in Alpaca" in msg for msg in warnings), "alpaca-only warning")
    assert_true(any("MSFT tracked as open" in msg for msg in warnings), "db-only warning")
    assert_true(logger.info.called, "summary logged")


def main():
    tests = [
        test_startup_service_runs_all_steps_even_when_one_fails,
        test_startup_reconcile_reports_position_mismatches,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} startup service tests passed.")


if __name__ == "__main__":
    main()
