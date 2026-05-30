#!/usr/bin/env python3
"""Characterization tests for legacy signal execution branches."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as _app
from tests.test_process_signal_rejections import _Env, _account, _buy, _sell, _PRICE


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy, got {value!r}")


class _StrategyResult:
    def __init__(self, score=80):
        self.score = score

    def to_dict(self):
        return {
            "trader_brain": {
                "score": self.score,
                "approved_by_scorer": True,
                "setup_type": "test",
                "reason": "test",
                "positive_factors": [],
                "risk_factors": [],
            }
        }


def _approved_downstream(**overrides):
    base = {
        "app.get_mock_account_state": MagicMock(return_value=_account(open_position_count=0)),
        "app.entry_policy.evaluate_session_momentum_gate": MagicMock(
            return_value={"would_block": False, "severity": "pass", "reason": "test"}
        ),
        "app.score_buy_opportunity": MagicMock(
            return_value={"score": 80, "bucket": "good", "decision": "allow", "size_multiplier": 1.0}
        ),
        "app.memory_for_signal": MagicMock(return_value={}),
        "app.build_intelligence_context": MagicMock(return_value={"summary": {}}),
        "app.evaluate_decision_policy": MagicMock(return_value={"decision": "allow"}),
        "app.public_decision_policy_config": MagicMock(return_value={"authority_mode": "test"}),
        "app.decision_policy_live_authority_enabled": MagicMock(return_value=False),
        "app._weekly_symbol_performance": MagicMock(return_value={}),
        "app.evaluate_strategy_observe_only": MagicMock(return_value=_StrategyResult()),
        "app._pre_order_safety_check": MagicMock(return_value=(True, "second-look ok")),
        "app._one_bar_confirmation_hold": MagicMock(return_value=(True, "one-bar ok")),
    }
    base.update(overrides)
    return base


def test_successful_approved_buy_submits_order_and_logs_trade():
    order = {"order_id": "order-1", "status": "submitted", "qty": 1, "fill_price": None}
    place_order = MagicMock(return_value=order)
    log_trade = MagicMock()
    write_cooldown = MagicMock()
    with _Env(**_approved_downstream(
        **{
            "app.evaluate_signal": MagicMock(
                return_value={
                    "approved": True,
                    "reason": "approved",
                    "confidence": "high",
                    "position_size_pct": 1.0,
                    "stop_loss_pct": 0.5,
                    "take_profit_pct": 1.5,
                }
            ),
            "app.place_order": place_order,
            "services.trade_audit_service.TradeAuditService.record_execution": log_trade,
            "app._write_cooldown": write_cooldown,
        }
    )):
        _app.process_signal(_buy(_dedupe_key="buy-ok"))

    assert_true(place_order.called, "broker order submitted")
    assert_true(write_cooldown.called, "cooldown written")
    assert_true(log_trade.called, "trade logged")
    assert_equal(log_trade.call_args.kwargs["decision"]["approved"], True, "logged approval")


def test_second_look_rejection_blocks_order_submission():
    place_order = MagicMock()
    with _Env(**_approved_downstream(
        **{
            "app.evaluate_signal": MagicMock(return_value={"approved": True, "confidence": "high", "position_size_pct": 1.0}),
            "app._pre_order_safety_check": MagicMock(return_value=(False, "spread too wide")),
            "app.place_order": place_order,
        }
    )) as env:
        _app.process_signal(_buy(_dedupe_key="second-look"))

    assert_equal(env.rejection_category(), "second_look", "category")
    assert_true(not place_order.called, "broker order not submitted")


def test_broker_order_failure_marks_decision_unapproved_and_submit_failed():
    log_trade = MagicMock()
    mark_status = MagicMock()
    with _Env(**_approved_downstream(
        **{
            "app.evaluate_signal": MagicMock(return_value={"approved": True, "confidence": "high", "position_size_pct": 1.0}),
            "app.place_order": MagicMock(return_value=None),
            "services.trade_audit_service.TradeAuditService.record_execution": log_trade,
            "services.trade_audit_service.TradeAuditService.record_webhook_status": mark_status,
        }
    )):
        _app.process_signal(_buy(_dedupe_key="broker-fail"))

    assert_true(log_trade.called, "failed order still logged")
    assert_equal(log_trade.call_args.kwargs["decision"]["approved"], False, "decision flipped")
    assert_equal(mark_status.call_args.kwargs["status"], "processed", "final webhook status")
    assert_true(
        any(call.kwargs.get("status") == "submit_failed" for call in mark_status.call_args_list),
        "submit_failed status recorded",
    )


def test_claude_low_confidence_rejection_never_submits_order():
    place_order = MagicMock()
    with _Env(**_approved_downstream(
        **{
            "app.evaluate_signal": MagicMock(
                return_value={"approved": True, "confidence": "low", "reason": "too weak"}
            ),
            "app.place_order": place_order,
        }
    )) as env:
        _app.process_signal(_buy())

    assert_equal(env.rejection_category(), "confidence_gate", "category")
    assert_true(not place_order.called, "broker order not submitted")


def test_weak_prediction_degraded_setup_sets_heavy_size_cap_before_claude():
    captured = {}

    def _capture_decision(signal, account_state):
        captured.update(account_state)
        return {"approved": False, "confidence": "medium", "reason": "stop"}

    with _Env(**_approved_downstream(
        **{
            "services.context_builder.build_setup_observation": MagicMock(
                return_value={
                    "setup_policy_action": "error",
                    "setup_label": None,
                    "setup_unknown_reason": "build_snapshot_failed",
                }
            ),
            "app.evaluate_signal_quality_gate": MagicMock(
                return_value={
                    "prediction_decision": "pass",
                    "ml_prediction_score": 40,
                    "ml_prediction_sample_size": 30,
                    "ml_prediction_confidence": "high",
                }
            ),
            "app.evaluate_signal": MagicMock(side_effect=_capture_decision),
        }
    )):
        _app.process_signal(_buy())

    assert_equal(captured["weak_prediction_setup_gate"]["triggered"], True, "weak gate")
    assert_equal(captured["max_position_size_pct_override"], 0.5, "size cap")


def test_unrecognized_setup_label_sets_size_cap_before_claude():
    captured = {}

    def _capture_decision(signal, account_state):
        captured.update(account_state)
        return {"approved": False, "confidence": "medium", "reason": "stop"}

    with _Env(**_approved_downstream(
        **{
            "services.context_builder.build_setup_observation": MagicMock(
                return_value={
                    "setup_policy_action": "neutral",
                    "setup_label": "brand_new_label",
                    "setup_unknown_reason": "unrecognized_label:brand_new_label",
                }
            ),
            "app.evaluate_signal": MagicMock(side_effect=_capture_decision),
        }
    )):
        _app.process_signal(_buy())

    assert_equal(captured["unrecognized_label_cap"]["cap_pct"], 0.85, "unrecognized cap")
    assert_equal(captured["max_position_size_pct_override"], 0.85, "size cap")


def test_session_hard_negative_rejection_when_enforced():
    with patch.object(_app, "ENFORCE_SESSION_MOMENTUM_GATE", True):
        with _Env(**_approved_downstream(
            **{
                "app.entry_policy.evaluate_session_momentum_gate": MagicMock(
                    return_value={
                        "would_block": True,
                        "severity": "hard_negative",
                        "reason": "down tape",
                    }
                ),
            }
        )) as env:
            _app.process_signal(_buy())

    assert_equal(env.rejection_category(), "session_momentum_gate", "category")


def test_strategy_weak_score_sets_size_cap_before_claude():
    captured = {}

    def _capture_decision(signal, account_state):
        captured.update(account_state)
        return {"approved": False, "confidence": "medium", "reason": "stop"}

    with _Env(**_approved_downstream(
        **{
            "app.evaluate_strategy_observe_only": MagicMock(return_value=_StrategyResult(score=30)),
            "app.evaluate_signal": MagicMock(side_effect=_capture_decision),
        }
    )):
        _app.process_signal(_buy())

    assert_equal(captured["strategy_score_size_cap"]["cap_pct"], 0.70, "strategy weak cap")


def test_buy_opportunity_cap_reduces_submitted_size():
    place_order = MagicMock(
        return_value={"order_id": "order-2", "status": "submitted", "qty": 1}
    )
    with _Env(**_approved_downstream(
        **{
            "app.evaluate_buy_opportunity": MagicMock(
                return_value={
                    "buy_opportunity_score": 5,
                    "buy_opportunity_recommendation": "watch",
                    "buy_opportunity_reason": "watch cap",
                }
            ),
            "app.evaluate_signal": MagicMock(
                return_value={
                    "approved": True,
                    "reason": "approved",
                    "confidence": "high",
                    "position_size_pct": 1.5,
                    "stop_loss_pct": 0.5,
                    "take_profit_pct": 1.5,
                }
            ),
            "app.place_order": place_order,
        }
    )):
        _app.process_signal(_buy())

    assert_equal(place_order.call_args.kwargs["position_size_pct"], 1.0, "watch cap")


def test_successful_approved_sell_submits_order_and_records_recent_sell():
    order = {"order_id": "sell-1", "status": "submitted", "qty": 1}
    place_order = MagicMock(return_value=order)
    write_recent_sell = MagicMock()
    existing_position = {"qty": 10, "current_price": _PRICE * 1.02, "avg_entry": _PRICE}
    with patch.object(_app.broker_service, "assert_position_exists", MagicMock()):
        with _Env(**_approved_downstream(
            **{
                "app.get_position": MagicMock(return_value=existing_position),
                "app._compute_trend": MagicMock(
                    return_value={
                        "direction": "bearish",
                        "strength": "confirmed",
                        "consecutive_count": 3,
                        "last_signal": "sell",
                        "flip_event": False,
                        "confirmed_entry": False,
                        "confirmed_exit": True,
                        "bullish_candidate": False,
                        "bearish_candidate": False,
                        "previous_opposite_count": 0,
                    }
                ),
                "app.evaluate_signal": MagicMock(
                    return_value={
                        "approved": True,
                        "reason": "approved sell",
                        "confidence": "high",
                        "position_size_pct": 0,
                    }
                ),
                "app.place_order": place_order,
                "app._write_recent_sell": write_recent_sell,
            }
        )):
            _app.process_signal(_sell())

    assert_true(place_order.called, "sell order submitted")
    assert_true(write_recent_sell.called, "recent sell written")


def test_portfolio_rotation_path_continues_after_slot_freed():
    get_account_state = MagicMock(
        side_effect=[
            _account(open_position_count=3),
            _account(open_position_count=0),
        ]
    )
    with patch("app.time.sleep", MagicMock()):
        with _Env(**_approved_downstream(
            **{
                "app.get_mock_account_state": get_account_state,
                "app.get_macro_risk": MagicMock(
                    return_value={"block_new_buys": False, "max_new_positions": 3, "reason": ""}
                ),
                "app._try_portfolio_rotation": MagicMock(
                    return_value=(True, "submitted rotation sell", {"weakest": {"symbol": "MSFT"}})
                ),
                "app.evaluate_signal": MagicMock(return_value={"approved": False, "confidence": "medium", "reason": "stop"}),
            }
        )) as env:
            _app.process_signal(_buy())

    assert_true(not env.rejected(), "rotation path did not reject at macro limit")


def main():
    tests = [
        test_successful_approved_buy_submits_order_and_logs_trade,
        test_second_look_rejection_blocks_order_submission,
        test_broker_order_failure_marks_decision_unapproved_and_submit_failed,
        test_claude_low_confidence_rejection_never_submits_order,
        test_weak_prediction_degraded_setup_sets_heavy_size_cap_before_claude,
        test_unrecognized_setup_label_sets_size_cap_before_claude,
        test_session_hard_negative_rejection_when_enforced,
        test_strategy_weak_score_sets_size_cap_before_claude,
        test_buy_opportunity_cap_reduces_submitted_size,
        test_successful_approved_sell_submits_order_and_records_recent_sell,
        test_portfolio_rotation_path_continues_after_slot_freed,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} legacy characterization tests passed.")


if __name__ == "__main__":
    main()
