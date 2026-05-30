#!/usr/bin/env python3
"""Unit tests for the object audit-service boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.trade_audit_service import TradeAuditService


def assert_true(value, label):
    if not value:
        raise AssertionError(label)


class _Logger:
    def warning(self, *_):
        pass

    def error(self, *_):
        pass


def _service(mark_status=None):
    return TradeAuditService(
        market_bias={},
        trend_table={},
        ml_prediction_bucket=lambda _: "unknown",
        log=_Logger(),
        mark_webhook_event_status=mark_status or MagicMock(),
    )


def test_record_rejection_delegates_through_service_boundary():
    with patch("services.trade_audit_service.log_rejection") as log_rejection:
        service = _service()
        service.record_rejection(
            symbol="AAPL",
            action="buy",
            category="confidence_gate",
            reason="low confidence",
            price=100,
            account_state={},
            dedupe_key="dedupe-1",
        )

    assert_true(log_rejection.called, "log_rejection delegated")


def test_record_execution_delegates_through_service_boundary():
    with patch("services.trade_audit_service.log_trade") as log_trade:
        service = _service()
        service.record_execution(
            signal={"symbol": "AAPL", "action": "buy", "price": 100},
            decision={"approved": True},
            order={"order_id": "order-1"},
            account_state={},
            dedupe_key="dedupe-1",
        )

    assert_true(log_trade.called, "log_trade delegated")


def main():
    tests = [
        test_record_rejection_delegates_through_service_boundary,
        test_record_execution_delegates_through_service_boundary,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} trade audit service tests passed.")


if __name__ == "__main__":
    main()
