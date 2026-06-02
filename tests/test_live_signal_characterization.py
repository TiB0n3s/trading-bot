#!/usr/bin/env python3
"""Characterization tests for live signal execution branches."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as _app
from services.persistent_lockout_service import LockoutState
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


class _LockedRegimeService:
    def __init__(self, _path):
        pass

    def read(self):
        return LockoutState(
            version="risk_lockout_state_v1",
            active=True,
            status="lockout",
            reason="test_regime_lockout",
            updated_at="2026-06-01T00:00:00+00:00",
            payload={},
        )


def _process_live(raw_signal):
    """Exercise LiveSignalProcessor.process directly, after normalizing inputs."""
    pipeline = _app._build_signal_pipeline()
    context = pipeline.normalize(raw_signal)
    runtime_state = pipeline.deps.build_runtime_state(context)
    context_runtime = pipeline.deps.build_context_runtime(runtime_state)
    preflight_result = pipeline.deps.evaluate_preflight(runtime_state)
    if not preflight_result.allowed:
        raise AssertionError(
            "test fixture hit preflight before LiveSignalProcessor: "
            f"{preflight_result.rejection_category} {preflight_result.rejection_reason}"
        )
    return pipeline.deps.live_signal_processor.process(
        context,
        runtime_state,
        context_runtime,
        preflight_result,
    )


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
            "app.broker_service.place_order": place_order,
            "services.trade_audit_service.TradeAuditService.record_execution": log_trade,
            "app._write_cooldown": write_cooldown,
        }
    )):
        _process_live(_buy(_dedupe_key="buy-ok"))

    assert_true(place_order.called, "broker order submitted")
    assert_true(write_cooldown.called, "cooldown written")
    assert_true(log_trade.called, "trade logged")
    assert_equal(log_trade.call_args.kwargs["decision"]["approved"], True, "logged approval")
    logged_state = log_trade.call_args.kwargs["account_state"]
    assert_true("final_sizing" in logged_state, "final sizing carried to audit")
    assert_equal(logged_state["final_sizing"]["dominant_limiter"], "uncapped", "audit limiter")
    assert_equal(logged_state["dominant_limiter"], "uncapped", "account-state limiter")


def test_stale_signal_rejection_stops_before_approval():
    evaluate_signal = MagicMock()
    with _Env(**_approved_downstream(
        **{
            "app._is_signal_stale": MagicMock(return_value=(True, 999.0, "too old")),
            "app.evaluate_signal": evaluate_signal,
        }
    )) as env:
        _process_live(_buy())

    assert_equal(env.rejection_category(), "stale_signal", "category")
    assert_true(not evaluate_signal.called, "approval not called")


def test_regime_circuit_breaker_blocks_buy_before_approval():
    evaluate_signal = MagicMock()
    with patch.dict(os.environ, {"REGIME_CIRCUIT_BREAKER_MODE": "block"}):
        with patch("services.signal_runtime_wiring.PersistentLockoutService", _LockedRegimeService):
            with _Env(**_approved_downstream(
                **{"app.evaluate_signal": evaluate_signal}
            )) as env:
                _process_live(_buy(_dedupe_key="regime-lockout"))

    assert_equal(env.rejection_category(), "circuit_breaker", "category")
    assert_true("regime circuit breaker" in env.rejection_reason(), "reason")
    assert_true(not evaluate_signal.called, "approval not called")


def test_second_look_rejection_blocks_order_submission():
    place_order = MagicMock()
    with _Env(**_approved_downstream(
        **{
            "app.evaluate_signal": MagicMock(return_value={"approved": True, "confidence": "high", "position_size_pct": 1.0}),
            "app._pre_order_safety_check": MagicMock(return_value=(False, "spread too wide")),
            "app.broker_service.place_order": place_order,
        }
    )) as env:
        _process_live(_buy(_dedupe_key="second-look"))

    assert_equal(env.rejection_category(), "second_look", "category")
    assert_true(not place_order.called, "broker order not submitted")


def test_broker_order_failure_marks_decision_unapproved_and_submit_failed():
    log_trade = MagicMock()
    mark_status = MagicMock()
    with _Env(**_approved_downstream(
        **{
            "app.evaluate_signal": MagicMock(return_value={"approved": True, "confidence": "high", "position_size_pct": 1.0}),
            "app.broker_service.place_order": MagicMock(return_value=None),
            "services.trade_audit_service.TradeAuditService.record_execution": log_trade,
            "services.trade_audit_service.TradeAuditService.record_webhook_status": mark_status,
        }
    )):
        _process_live(_buy(_dedupe_key="broker-fail"))

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
            "app.broker_service.place_order": place_order,
        }
    )) as env:
        _process_live(_buy())

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
        _process_live(_buy())

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
        _process_live(_buy())

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
            _process_live(_buy())

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
        _process_live(_buy())

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
            "app.broker_service.place_order": place_order,
        }
    )):
        _process_live(_buy())

    assert_equal(place_order.call_args.kwargs["position_size_pct"], 1.0, "watch cap")


def test_late_chase_entry_sets_heavy_size_cap_before_claude():
    captured = {}

    def _capture_decision(signal, account_state):
        captured.update(account_state)
        return {"approved": False, "confidence": "medium", "reason": "stop"}

    with _Env(**_approved_downstream(
        **{
            "app.rolling_symbol_context": MagicMock(
                return_value={
                    "special_labels": ["extended_above_recent_base"],
                    "extension_from_recent_base_pct": 5.5,
                }
            ),
            "app.get_latest_session_momentum": MagicMock(
                return_value={
                    "trend_label": "uptrend",
                    "trend_score": 4,
                    "session_return_pct": 0.6,
                    "momentum_15m_pct": 0.1,
                    "momentum_30m_pct": 0.2,
                    "distance_from_vwap_pct": 1.3,
                }
            ),
            "app._session_momentum_is_fresh": MagicMock(return_value=True),
            "services.context_builder.build_setup_observation": MagicMock(
                return_value={
                    "setup_policy_action": "neutral",
                    "setup_label": "above_vwap_neutral_continuation",
                    "setup_score": 50,
                }
            ),
            "app.evaluate_signal": MagicMock(side_effect=_capture_decision),
        }
    )):
        _process_live(_buy(_dedupe_key="late-chase-cap"))

    assert_equal(captured["late_chase_entry_gate"]["triggered"], True, "late chase gate")
    assert_equal(captured["late_chase_size_cap"]["cap_pct"], 0.5, "late chase cap")
    assert_equal(captured["max_position_size_pct_override"], 0.5, "size cap")


def test_extreme_late_chase_entry_rejects_before_claude():
    evaluate_signal = MagicMock()
    with _Env(**_approved_downstream(
        **{
            "app.rolling_symbol_context": MagicMock(
                return_value={
                    "special_labels": ["gap_up_chase_risk"],
                    "extension_from_recent_base_pct": 8.5,
                }
            ),
            "app.get_latest_session_momentum": MagicMock(
                return_value={
                    "trend_label": "fading",
                    "trend_score": -2,
                    "session_return_pct": 1.2,
                    "momentum_15m_pct": -0.1,
                    "momentum_30m_pct": -0.2,
                    "distance_from_vwap_pct": 1.9,
                }
            ),
            "app._session_momentum_is_fresh": MagicMock(return_value=True),
            "services.context_builder.build_setup_observation": MagicMock(
                return_value={
                    "setup_policy_action": "neutral",
                    "setup_label": "late_strength_near_vwap_risk",
                    "setup_score": 42,
                }
            ),
            "app.evaluate_signal": evaluate_signal,
        }
    )) as env:
        _process_live(_buy(_dedupe_key="late-chase-block"))

    assert_equal(env.rejection_category(), "late_chase_entry", "category")
    assert_true(not evaluate_signal.called, "approval not called")


def test_unclassified_extended_entry_sets_heavy_size_cap_before_claude():
    captured = {}

    def _capture_decision(signal, account_state):
        captured.update(account_state)
        return {"approved": False, "confidence": "medium", "reason": "stop"}

    with _Env(**_approved_downstream(
        **{
            "app.get_latest_session_momentum": MagicMock(
                return_value={
                    "trend_label": "strong_uptrend",
                    "trend_score": 8,
                    "session_return_pct": 2.2,
                    "momentum_15m_pct": 1.0,
                    "momentum_30m_pct": 1.8,
                    "distance_from_vwap_pct": 1.65,
                }
            ),
            "app._session_momentum_is_fresh": MagicMock(return_value=True),
            "services.context_builder.build_setup_observation": MagicMock(
                return_value={
                    "setup_policy_action": "neutral",
                    "setup_label": "unclassified_transition",
                    "setup_score": 35,
                }
            ),
            "app.evaluate_signal": MagicMock(side_effect=_capture_decision),
        }
    )):
        _process_live(_buy(_dedupe_key="unclassified-extended-cap"))

    assert_equal(captured["unclassified_extended_size_cap"]["cap_pct"], 0.35, "cap")
    assert_equal(captured["max_position_size_pct_override"], 0.35, "size cap")


def test_extreme_unclassified_extended_entry_rejects_before_claude():
    evaluate_signal = MagicMock()
    with _Env(**_approved_downstream(
        **{
            "app.get_latest_session_momentum": MagicMock(
                return_value={
                    "trend_label": "strong_uptrend",
                    "trend_score": 8,
                    "session_return_pct": 3.0,
                    "momentum_15m_pct": 1.0,
                    "momentum_30m_pct": 1.8,
                    "distance_from_vwap_pct": 2.35,
                }
            ),
            "app._session_momentum_is_fresh": MagicMock(return_value=True),
            "services.context_builder.build_setup_observation": MagicMock(
                return_value={
                    "setup_policy_action": "neutral",
                    "setup_label": "unclassified_transition",
                    "setup_score": 35,
                }
            ),
            "app.evaluate_signal": evaluate_signal,
        }
    )) as env:
        _process_live(_buy(_dedupe_key="unclassified-extended-block"))

    assert_equal(env.rejection_category(), "unclassified_extended_entry", "category")
    assert_true(not evaluate_signal.called, "approval not called")


def test_successful_approved_sell_submits_order_and_records_recent_sell():
    order = {"order_id": "sell-1", "status": "submitted", "qty": 1}
    place_order = MagicMock(return_value=order)
    write_recent_sell = MagicMock()
    existing_position = {"qty": 10, "current_price": _PRICE * 1.02, "avg_entry": _PRICE}
    with patch.object(_app.broker_service, "assert_position_exists", MagicMock()):
        with _Env(**_approved_downstream(
            **{
                "app.broker_service.get_position": MagicMock(return_value=existing_position),
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
                "app.broker_service.place_order": place_order,
                "app._write_recent_sell": write_recent_sell,
            }
        )):
            _process_live(_sell())

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
            _process_live(_buy())

    assert_true(not env.rejected(), "rotation path did not reject at macro limit")


def main():
    tests = [
        test_successful_approved_buy_submits_order_and_logs_trade,
        test_stale_signal_rejection_stops_before_approval,
        test_regime_circuit_breaker_blocks_buy_before_approval,
        test_second_look_rejection_blocks_order_submission,
        test_broker_order_failure_marks_decision_unapproved_and_submit_failed,
        test_claude_low_confidence_rejection_never_submits_order,
        test_weak_prediction_degraded_setup_sets_heavy_size_cap_before_claude,
        test_unrecognized_setup_label_sets_size_cap_before_claude,
        test_session_hard_negative_rejection_when_enforced,
        test_strategy_weak_score_sets_size_cap_before_claude,
        test_buy_opportunity_cap_reduces_submitted_size,
        test_late_chase_entry_sets_heavy_size_cap_before_claude,
        test_extreme_late_chase_entry_rejects_before_claude,
        test_unclassified_extended_entry_sets_heavy_size_cap_before_claude,
        test_extreme_unclassified_extended_entry_rejects_before_claude,
        test_successful_approved_sell_submits_order_and_records_recent_sell,
        test_portfolio_rotation_path_continues_after_slot_freed,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} live signal characterization tests passed.")


if __name__ == "__main__":
    main()
