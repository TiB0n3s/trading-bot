#!/usr/bin/env python3
"""Phase 0 characterization tests for the Flask composition root."""

from __future__ import annotations

import os
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ALPACA_API_KEY", "test-key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test-secret")
os.environ.setdefault("APCA_API_KEY_ID", "test-key")
os.environ.setdefault("APCA_API_SECRET_KEY", "test-secret")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("EXECUTION_MODE", "paper")

import app as _app


SECRET_HEADERS = {"X-Webhook-Secret": os.environ["WEBHOOK_SECRET"]}


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


class _PatchMany:
    def __init__(self, patches: dict):
        self.patches = patches
        self.stack = ExitStack()

    def __enter__(self):
        for target, value in self.patches.items():
            self.stack.enter_context(patch(target, new=value))
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stack.close()


def test_create_app_returns_isolated_app_without_startup():
    with patch("app.run_startup_tasks", MagicMock()) as startup:
        flask_app = _app.create_app(run_startup=False)

    assert_true(flask_app is not _app.app, "create_app returns isolated Flask app")
    assert_true(not startup.called, "run_startup_tasks not called")
    assert_true(not _app._STARTUP_TASKS_RAN, "startup flag remains false")
    assert_true(_app._signal_executor is None, "signal executor not created at import")
    rules = {str(rule) for rule in flask_app.url_map.iter_rules()}
    for route in {"/health", "/status", "/positions", "/debug/symbol/<symbol>"}:
        assert_true(route in rules, f"{route} registered")


def test_create_app_can_run_explicit_startup():
    with patch("app.run_startup_tasks", MagicMock()) as startup:
        _app.create_app(run_startup=True)
    assert_true(startup.called, "run_startup_tasks called explicitly")


def test_create_app_exposes_explicit_container():
    flask_app = _app.create_app(app_container=_app.container)
    assert_true(
        flask_app.extensions["application_container"] is _app.container,
        "explicit container attached to Flask app",
    )


def test_health_route_snapshot():
    flask_app = _app.create_app()
    flask_app.testing = True
    with patch("app.broker_service.get_account", MagicMock(return_value={"buying_power": 123.45})):
        resp = flask_app.test_client().get("/health")
    assert_equal(resp.status_code, 200, "health status")
    data = resp.get_json()
    assert_equal(data["status"], "online", "health status payload")
    assert_equal(data["account"]["buying_power"], 123.45, "health account payload")


def test_status_route_snapshot():
    flask_app = _app.create_app()
    flask_app.testing = True
    patches = {
        "services.status_service._session_momentum_summary": MagicMock(return_value={}),
        "services.status_service._session_momentum_snapshot": MagicMock(return_value=[]),
        "services.status_service._symbol_intelligence_snapshot": MagicMock(
            return_value={"available": False, "symbols": {}}
        ),
        "app.policy_artifact_status": MagicMock(return_value={"available": False}),
        "app.get_macro_risk": MagicMock(return_value={"macro_regime": "normal", "max_new_positions": 8}),
        "app.rolling_summary": MagicMock(return_value={"available": False}),
        "app.get_mock_account_state": MagicMock(
            return_value={
                "balance": 100000.0,
                "portfolio_value": 100000.0,
                "daily_pnl": 0.0,
                "daily_pnl_pct": 0.0,
            }
        ),
        "app.broker_service.get_account": MagicMock(return_value={"buying_power": 50000.0}),
        "app.ledger_summary": MagicMock(return_value={"rows": 0}),
        "app.broker_service.list_positions": MagicMock(return_value=[]),
        "app.get_intelligence_snapshot": MagicMock(return_value={"available": False}),
    }
    with _PatchMany(patches):
        resp = flask_app.test_client().get("/status", headers=SECRET_HEADERS)

    assert_equal(resp.status_code, 200, "status status")
    data = resp.get_json()
    for key in ("execution_mode", "runtime_config", "prediction_gate_mode", "portfolio_rotation"):
        assert_true(key in data, f"status contains {key}")


def test_positions_route_snapshot():
    flask_app = _app.create_app()
    flask_app.testing = True
    patches = {
        "app.get_mock_account_state": MagicMock(
            return_value={"balance": 100000.0, "daily_pnl_pct": 0.0}
        ),
        "app.broker_service.list_positions": MagicMock(return_value=[]),
        "app._load_market_context": MagicMock(),
    }
    with _PatchMany(patches):
        resp = flask_app.test_client().get("/positions", headers=SECRET_HEADERS)

    assert_equal(resp.status_code, 200, "positions status")
    data = resp.get_json()
    assert_equal(data["summary"]["total_positions"], 0, "positions summary")
    assert_equal(data["summary"]["max_positions"], _app.MAX_OPEN_POSITIONS, "positions max")
    assert_equal(data["positions"], [], "positions list")


def test_debug_symbol_route_snapshot():
    flask_app = _app.create_app()
    flask_app.testing = True
    symbol = sorted(_app.APPROVED_SYMBOLS)[0]
    patches = {
        "app._load_market_context": MagicMock(),
        "app.now_et": MagicMock(return_value=_app.datetime(2026, 5, 29, 10, 0, tzinfo=_app.ET)),
        "app.is_market_hours": MagicMock(return_value=True),
        "app.get_mock_account_state": MagicMock(
            return_value={
                "balance": 100000.0,
                "portfolio_value": 100000.0,
                "daily_pnl": 0.0,
                "daily_pnl_pct": 0.0,
                "open_position_count": 0,
            }
        ),
        "app.broker_service.get_position": MagicMock(return_value=None),
        "app._successful_buys_today": MagicMock(return_value=0),
        "app._read_cooldown": MagicMock(return_value=None),
        "app._read_recent_sell": MagicMock(return_value=None),
        "app._cluster_exposure": MagicMock(return_value=[]),
        "app.get_macro_risk": MagicMock(return_value={"macro_regime": "normal"}),
        "app.rolling_symbol_context": MagicMock(return_value=None),
        "app._symbol_market_alignment": MagicMock(return_value={}),
        "services.debug_symbol_service.symbol_intelligence_for_symbol": MagicMock(return_value=None),
        "app._required_buy_confirmations": MagicMock(return_value={"required_buy_confirmations": 3}),
        "app._required_sell_confirmations": MagicMock(return_value={"required_sell_confirmations": 2}),
    }
    with _PatchMany(patches):
        resp = flask_app.test_client().get(f"/debug/symbol/{symbol}", headers=SECRET_HEADERS)

    assert_equal(resp.status_code, 200, "debug symbol status")
    data = resp.get_json()
    assert_equal(data["symbol"], symbol, "debug symbol payload")
    assert_true("buy_would_pass_known_prechecks" in data, "debug precheck payload")


if __name__ == "__main__":
    tests = [
        test_create_app_returns_isolated_app_without_startup,
        test_create_app_can_run_explicit_startup,
        test_create_app_exposes_explicit_container,
        test_health_route_snapshot,
        test_status_route_snapshot,
        test_positions_route_snapshot,
        test_debug_symbol_route_snapshot,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} Phase 0 app tests passed.")
