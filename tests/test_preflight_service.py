#!/usr/bin/env python3
"""Unit tests for deterministic preflight gates."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.preflight_service import (
    PreflightDeps,
    PreflightService,
    normalize_signal_identity,
)
from services.signal_models import SignalRuntimeState


NOW = datetime(2024, 6, 10, 11, 30, tzinfo=timezone.utc)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def _state(action="buy", account_state=None):
    return SignalRuntimeState(
        raw_signal={"symbol": "AAPL", "action": action, "price": 100.0},
        symbol="AAPL",
        action=action,
        received_at=NOW,
        account_state=account_state or {"balance": 100000.0, "daily_pnl_pct": 0.0},
    )


def _deps(**overrides):
    base = {
        "now_et": lambda: NOW,
        "is_market_hours": lambda now: True,
        "assert_position_exists": lambda symbol: None,
        "get_position": lambda symbol: None,
        "read_cooldown": lambda symbol, action: None,
        "read_recent_sell": lambda symbol: None,
        "is_duplicate_webhook": lambda symbol, action, price: False,
        "adaptive_churn_reentry_allowed": lambda **kwargs: (False, "test"),
        "successful_buys_today": lambda symbol: 0,
        "filled_buys_today": lambda symbol: 0,
        "cluster_exposure": lambda symbol, balance: [],
        "max_buys_per_symbol_per_day": 2,
        "session_max_trade_count": 3,
        "webhook_dedupe_seconds": 60,
        "daily_loss_limit_pct": -3.0,
    }
    base.update(overrides)
    return PreflightDeps(**base)


def test_duplicate_webhook_rejects_before_other_checks():
    service = PreflightService(_deps(is_duplicate_webhook=lambda *_: True))
    result = service.evaluate(_state())
    assert_equal(result.allowed, False, "allowed")
    assert_equal(result.rejection_category, "duplicate_webhook", "category")


def test_normalize_signal_identity():
    symbol, action = normalize_signal_identity({"symbol": " aapl ", "action": " BUY "})
    assert_equal(symbol, "AAPL", "symbol")
    assert_equal(action, "buy", "action")


def test_cooldown_rejection():
    service = PreflightService(_deps(read_cooldown=lambda *_: NOW - timedelta(minutes=5)))
    result = service.evaluate(_state())
    assert_equal(result.allowed, False, "allowed")
    assert_equal(result.rejection_category, "cooldown", "category")


def test_churn_price_rejection():
    service = PreflightService(
        _deps(read_recent_sell=lambda symbol: (NOW - timedelta(minutes=45), 100.1))
    )
    result = service.evaluate(_state())
    assert_equal(result.allowed, False, "allowed")
    assert_equal(result.rejection_category, "churn_price", "category")


def test_allowed_result_carries_existing_position_and_cluster_metadata():
    position = {"qty": 1, "current_price": 100.0}
    cluster = [{"cluster": "tech", "limit_hit": False, "exposure_pct": 1.2}]
    state = _state()
    service = PreflightService(
        _deps(
            get_position=lambda symbol: position,
            cluster_exposure=lambda symbol, balance: cluster,
        )
    )
    result = service.evaluate(state)
    assert_equal(result.allowed, True, "allowed")
    assert_equal(result.metadata["existing_position"], position, "existing position")
    assert_equal(state.account_state["correlation_exposure"], cluster, "cluster state")


def main():
    tests = [
        test_duplicate_webhook_rejects_before_other_checks,
        test_normalize_signal_identity,
        test_cooldown_rejection,
        test_churn_price_rejection,
        test_allowed_result_carries_existing_position_and_cluster_metadata,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} preflight service tests passed.")


if __name__ == "__main__":
    main()
