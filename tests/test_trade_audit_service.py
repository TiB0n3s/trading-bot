#!/usr/bin/env python3
"""Unit tests for the object audit-service boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

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
        ml_prediction_bucket=lambda score: "weak_below_45" if score == 42 else "unknown",
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


def test_record_execution_persists_conviction_sizing_and_prediction_fields():
    captured = {}

    def _insert(columns, values):
        captured.update(dict(zip(columns, values)))
        return 123

    account_state = {
        "setup_observation": {
            "setup_policy_action": "allow",
            "setup_label": "confirmed_near_vwap_recovery",
        },
        "prediction_gate": {
            "ml_prediction_score": 42,
            "ml_prediction_bucket": "weak_below_45",
            "prediction_decision": "pass",
        },
        "buy_opportunity": {
            "buy_opportunity_score": 12,
            "buy_opportunity_recommendation": "watch",
        },
        "strategy_observation": {
            "trader_brain": {
                "score": 64,
                "setup_type": "trend_pullback",
                "approved_by_scorer": True,
            },
        },
        "session_momentum": {
            "trend_label": "strong_uptrend",
            "trend_score": 7,
            "momentum_60m_pct": 1.2,
            "momentum_120m_pct": 1.8,
            "trend_regime": "mature_uptrend",
            "trend_persistence_score": 5,
            "pullback_with_trend_score": 1,
            "late_chase_maturity_score": 4,
            "reversal_attempt_score": 0,
        },
        "final_sizing": {
            "dominant_limiter": "weak_prediction_degraded",
            "active_caps": [
                {"source": "weak_prediction_degraded", "cap_pct": 0.5},
                {"source": "session_momentum", "cap_pct": 0.8},
            ],
            "conviction_stack": {
                "session_severity": "pass",
                "effective_cap_pct": 0.5,
            },
        },
    }

    with (
        patch("builtins.open", mock_open()),
        patch("services.trade_audit_service.trades_repo.insert_trade_row", side_effect=_insert),
        patch("services.trade_audit_service.snapshots_repo.record_snapshot"),
    ):
        _service().record_execution(
            signal={"symbol": "AAPL", "action": "buy", "price": 100},
            decision={"approved": True, "position_size_pct": 1.0},
            order={"order_id": "order-1", "status": "submitted", "qty": 1},
            account_state=account_state,
        )

    assert_true(captured["effective_size_cap_pct"] == 0.5, "effective size cap persisted")
    assert_true(
        captured["dominant_limiter"] == "weak_prediction_degraded",
        "dominant limiter persisted",
    )
    assert_true(captured["ml_prediction_bucket"] == "weak_below_45", "ML bucket persisted")
    assert_true(captured["ml_prediction_score"] == 42, "ML score persisted")
    assert_true(captured["buy_opportunity_recommendation"] == "watch", "buy opportunity persisted")
    assert_true(captured["trader_brain_score"] == 64, "strategy score persisted")
    assert_true(captured["session_trend_label"] == "strong_uptrend", "session label persisted")
    assert_true(captured["session_momentum_60m_pct"] == 1.2, "session 60m persisted")
    assert_true(captured["session_momentum_120m_pct"] == 1.8, "session 120m persisted")
    assert_true(captured["session_trend_regime"] == "mature_uptrend", "session regime persisted")
    assert_true(captured["late_chase_maturity_score"] == 4, "maturity score persisted")
    assert_true(captured["setup_policy_action"] == "allow", "setup action persisted")


def main():
    tests = [
        test_record_rejection_delegates_through_service_boundary,
        test_record_execution_delegates_through_service_boundary,
        test_record_execution_persists_conviction_sizing_and_prediction_fields,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} trade audit service tests passed.")


if __name__ == "__main__":
    main()
