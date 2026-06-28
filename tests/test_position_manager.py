"""
Focused tests for position-manager exit guards.

Run:
  python3 tests/test_position_manager.py
"""
# ruff: noqa: E402

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ALPACA_API_KEY", "test-key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test-secret")

import position_manager
from position_manager import (
    continuation_exit_delay_reason,
    exit_pattern_pressure_state,
    is_auto_buy_entry,
    is_high_confidence_auto_buy_entry,
    is_strong_conviction_entry,
    is_weak_entry_context,
    normalize_exit_for_share_qty,
    peak_aware_breakeven_floor,
    planned_partial_sell_qty,
    proactive_profit_capture_trigger,
)


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value, got {value!r}")


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_continuation_delays_soft_full_exit_when_tape_supports():
    reason = continuation_exit_delay_reason(
        current_pl_pct=-0.20,
        momentum_15m=0.12,
        momentum_30m=0.08,
        vwap_dist_pct=0.03,
    )

    assert_true(reason, "delay reason")
    assert_true("full exit delayed" in reason, "reason text")


def test_continuation_does_not_delay_hard_loss():
    reason = continuation_exit_delay_reason(
        current_pl_pct=-0.90,
        momentum_15m=0.12,
        momentum_30m=0.08,
        vwap_dist_pct=0.10,
    )

    assert_equal(reason, None, "hard loss delay")


def test_partial_exit_promotes_to_full_when_position_is_one_share():
    reasons = ["profit giveback trigger"]

    action, sell_fraction, severity = normalize_exit_for_share_qty(
        action="sell_partial",
        sell_fraction=0.50,
        qty=1,
        severity="medium",
        reasons=reasons,
    )

    assert_equal(action, "sell_full", "action")
    assert_equal(sell_fraction, 1.0, "sell fraction")
    assert_equal(severity, "high", "severity")
    assert_true("partial_exit_promoted_to_full" in reasons[-1], "promotion reason")


def test_partial_exit_remains_partial_when_share_qty_is_actionable():
    reasons = ["profit giveback trigger"]

    action, sell_fraction, severity = normalize_exit_for_share_qty(
        action="sell_partial",
        sell_fraction=0.50,
        qty=8,
        severity="medium",
        reasons=reasons,
    )

    assert_equal(action, "sell_partial", "action")
    assert_equal(sell_fraction, 0.50, "sell fraction")
    assert_equal(severity, "medium", "severity")
    assert_equal(planned_partial_sell_qty(8, 0.50), 4, "planned qty")


def test_weak_entry_peak_lock_tier2_protects_more_profit():
    floor = peak_aware_breakeven_floor(peak_pl_pct=0.70, weak_entry=True)

    assert_equal(floor, 0.35, "weak entry tier2 floor")


def test_strong_entry_peak_lock_tiers_keep_more_profit():
    assert_equal(
        peak_aware_breakeven_floor(peak_pl_pct=0.70, weak_entry=False),
        0.30,
        "strong tier2 floor",
    )
    assert_equal(
        peak_aware_breakeven_floor(peak_pl_pct=1.20, weak_entry=False),
        0.45,
        "strong tier3 floor",
    )


def test_neutral_and_late_strength_entries_are_weak_context():
    assert_true(
        is_weak_entry_context({"entry_setup_label": "above_vwap_neutral_continuation"}),
        "neutral continuation weak",
    )
    assert_true(
        is_weak_entry_context({"entry_setup_label": "late_strength_near_vwap_risk"}),
        "late strength weak",
    )


def test_strong_conviction_requires_allow_or_boost_setup():
    entry_ctx = {
        "entry_ml_prediction_bucket": "high_55_plus",
        "entry_buy_opportunity_recommendation": "strong_buy_candidate",
        "entry_buy_opportunity_score": 12,
        "entry_setup_policy_action": "neutral",
    }

    assert_equal(is_strong_conviction_entry(entry_ctx), False, "neutral not strong")
    entry_ctx["entry_setup_policy_action"] = "allow"
    assert_equal(is_strong_conviction_entry(entry_ctx), True, "allow strong")


def test_auto_buy_entry_detection_uses_confidence_metadata():
    entry_ctx = {
        "entry_confidence": "auto_buy_manager",
        "entry_setup_label": "unclassified_transition",
        "entry_ml_prediction_score": 68.2,
    }

    assert_equal(is_auto_buy_entry(entry_ctx), True, "auto buy entry")
    assert_equal(
        is_high_confidence_auto_buy_entry(entry_ctx),
        True,
        "high-confidence auto buy entry",
    )


def test_proactive_profit_capture_triggers_while_still_green():
    triggered, reason = proactive_profit_capture_trigger(
        peak_pl_pct=0.55,
        current_pl_pct=0.24,
        giveback_pct=56.4,
        weak_entry=False,
        retained_strength={"retained": False},
    )

    assert_equal(triggered, True, "strong proactive trigger")
    assert_true("proactive_profit_capture" in reason, "reason text")


def test_proactive_profit_capture_triggers_faster_for_weak_entries():
    triggered, reason = proactive_profit_capture_trigger(
        peak_pl_pct=0.35,
        current_pl_pct=0.16,
        giveback_pct=54.3,
        weak_entry=True,
        retained_strength={"retained": True},
    )

    assert_equal(triggered, True, "weak proactive trigger")
    assert_true("weak_entry=True" in reason, "weak reason")


def test_proactive_profit_capture_respects_retained_strength_room():
    triggered, reason = proactive_profit_capture_trigger(
        peak_pl_pct=0.80,
        current_pl_pct=0.42,
        giveback_pct=47.5,
        weak_entry=False,
        retained_strength={"retained": True, "broken": False},
    )

    assert_equal(triggered, False, "retained strength delay")
    assert_true("retained session strength" in reason, "retained reason")


def test_exit_pattern_pressure_triggers_on_green_winner_rollover():
    pressure = exit_pattern_pressure_state(
        peak_pl_pct=0.65,
        current_pl_pct=0.22,
        giveback_pct=66.2,
        momentum_5m=-0.12,
        momentum_15m=-0.08,
        momentum_30m=0.02,
        vwap_dist_pct=0.02,
        weak_entry=False,
        retained_strength={"retained": False, "broken": False},
        entry_ctx={"entry_ml_prediction_bucket": "mid_50_55"},
    )

    assert_equal(pressure["triggered"], True, "triggered")
    assert_equal(pressure["action_hint"], "sell_partial", "action hint")
    assert_true("5m_rollover" in pressure["reason"], "5m pressure")
    assert_true("15m_rollover" in pressure["reason"], "15m pressure")


def test_exit_pattern_pressure_gives_retained_strength_extra_confirmation():
    pressure = exit_pattern_pressure_state(
        peak_pl_pct=0.80,
        current_pl_pct=0.45,
        giveback_pct=43.8,
        momentum_5m=-0.12,
        momentum_15m=-0.08,
        momentum_30m=0.18,
        vwap_dist_pct=0.15,
        weak_entry=False,
        retained_strength={"retained": True, "broken": False},
        entry_ctx={"entry_ml_prediction_bucket": "high_55_plus"},
    )

    assert_equal(pressure["triggered"], False, "triggered")
    assert_equal(pressure["action_hint"], "hold", "action hint")
    assert_true("retained_session_strength" in pressure["reason"], "retained context")


def test_exit_pattern_pressure_is_not_armed_before_profit_threshold():
    pressure = exit_pattern_pressure_state(
        peak_pl_pct=0.20,
        current_pl_pct=0.09,
        giveback_pct=55.0,
        momentum_5m=-0.20,
        momentum_15m=-0.20,
        momentum_30m=-0.20,
        vwap_dist_pct=-0.20,
        weak_entry=False,
        retained_strength={"retained": False, "broken": False},
        entry_ctx={},
    )

    assert_equal(pressure["triggered"], False, "triggered")
    assert_equal(pressure["state"], "not_armed", "state")


def test_evaluate_position_uses_exit_pattern_pressure_for_partial_profit_capture():
    class _Position:
        symbol = "AAPL"
        qty = 10
        avg_entry_price = 100.0
        current_price = 100.3
        unrealized_pl = 3.0
        unrealized_plpc = 0.003

    old_fetch = position_manager.fetch_intraday_bars
    old_entry = position_manager.get_entry_context
    try:
        position_manager.fetch_intraday_bars = lambda symbol, minutes=90: (
            [{"high": 101.0, "low": 100.8, "close": 100.9, "volume": 1000} for _ in range(80)]
            + [{"high": 100.6, "low": 100.2, "close": 100.3, "volume": 1000} for _ in range(10)]
        )
        position_manager.get_entry_context = lambda symbol: {
            "entry_setup_policy_action": "allow",
            "entry_ml_prediction_bucket": "mid_50_55",
            "entry_buy_opportunity_recommendation": "strong_buy_candidate",
            "entry_buy_opportunity_score": 12,
        }
        decision = position_manager.evaluate_position(
            _Position(),
            {
                "AAPL": {
                    "peak_pl_pct": 0.75,
                    "peak_price": 100.75,
                    "proactive_profit_capture_peak_pct": 0.75,
                }
            },
            session_momentum={"trend_label": "uptrend", "trend_score": 2},
        )
    finally:
        position_manager.fetch_intraday_bars = old_fetch
        position_manager.get_entry_context = old_entry

    assert_equal(decision["action"], "sell_partial", "action")
    assert_equal(
        decision["exit_pattern_pressure"]["state"],
        "profit_failure_pressure",
        "pressure state",
    )
    assert_true(
        any("exit_pattern_pressure" in reason for reason in decision["reasons"]),
        "exit pattern reason",
    )


def test_fresh_auto_buy_min_hold_suppresses_soft_peak_lock():
    class _Position:
        symbol = "AVGO"
        qty = 4
        avg_entry_price = 100.0
        current_price = 100.02
        unrealized_pl = 0.08
        unrealized_plpc = 0.0002

    old_fetch = position_manager.fetch_intraday_bars
    old_entry = position_manager.get_entry_context
    try:
        position_manager.fetch_intraday_bars = lambda symbol, minutes=90: (
            [{"high": 100.8, "low": 100.1, "close": 100.5, "volume": 1000} for _ in range(70)]
            + [{"high": 100.2, "low": 100.0, "close": 100.02, "volume": 1000} for _ in range(20)]
        )
        position_manager.get_entry_context = lambda symbol: {
            "entry_timestamp": (datetime.now(position_manager.ET) - timedelta(minutes=2)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "entry_confidence": "auto_buy_manager",
            "entry_setup_label": "unclassified_transition",
            "entry_setup_policy_action": "allow",
            "entry_ml_prediction_score": 68.2,
            "entry_ml_prediction_bucket": "high_55_plus",
            "entry_buy_opportunity_recommendation": "strong_buy_candidate",
            "entry_buy_opportunity_score": 12,
        }
        decision = position_manager.evaluate_position(
            _Position(),
            {"AVGO": {"peak_pl_pct": 0.80, "peak_price": 100.80}},
            session_momentum={"trend_label": "uptrend", "trend_score": 2},
        )
    finally:
        position_manager.fetch_intraday_bars = old_fetch
        position_manager.get_entry_context = old_entry

    assert_equal(decision["action"], "hold", "action")
    assert_equal(decision["auto_buy_min_hold"]["active"], True, "min-hold active")
    assert_equal(decision["raw_weak_entry_context"], True, "raw weak context")
    assert_equal(decision["weak_entry_context"], False, "high-confidence weak override")
    assert_true(
        any("suppressed sell_full" in reason for reason in decision["reasons"]),
        "suppressed sell reason",
    )


def test_fresh_auto_buy_min_hold_does_not_suppress_severe_loss_exit():
    class _Position:
        symbol = "AVGO"
        qty = 4
        avg_entry_price = 100.0
        current_price = 98.50
        unrealized_pl = -6.0
        unrealized_plpc = -0.015

    old_fetch = position_manager.fetch_intraday_bars
    old_entry = position_manager.get_entry_context
    try:
        position_manager.fetch_intraday_bars = lambda symbol, minutes=90: [
            {"high": 100.1, "low": 98.5, "close": 98.5, "volume": 1000} for _ in range(90)
        ]
        position_manager.get_entry_context = lambda symbol: {
            "entry_timestamp": (datetime.now(position_manager.ET) - timedelta(minutes=2)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "entry_confidence": "auto_buy_manager",
            "entry_setup_policy_action": "allow",
            "entry_ml_prediction_score": 68.2,
            "entry_ml_prediction_bucket": "high_55_plus",
        }
        decision = position_manager.evaluate_position(
            _Position(),
            {"AVGO": {"peak_pl_pct": 0.0, "peak_price": 100.0}},
            session_momentum={},
        )
    finally:
        position_manager.fetch_intraday_bars = old_fetch
        position_manager.get_entry_context = old_entry

    assert_equal(decision["action"], "sell_full", "action")
    assert_equal(decision["auto_buy_min_hold"]["severe_loss"], True, "severe loss")
    assert_equal(decision["auto_buy_min_hold"]["active"], False, "min-hold inactive")


def test_submit_partial_exit_defers_only_when_cancellation_does_not_settle():
    """If canceled brackets never clear, defer (do not blindly sell)."""

    class _Order:
        id = "open-order-1"

    class _Broker:
        def __init__(self):
            self.canceled = []
            self.submitted = False

        def list_open_orders(self, symbol):
            return [_Order()]  # never clears

        def cancel_order(self, order_id):
            self.canceled.append(order_id)

        def submit_market_sell(self, symbol, qty):
            self.submitted = True
            raise AssertionError("submit_market_sell should not run if orders never clear")

    broker = _Broker()
    old_broker = position_manager.broker_service
    old_attempts = position_manager._PARTIAL_CANCEL_POLL_ATTEMPTS
    old_delay = position_manager._PARTIAL_CANCEL_POLL_DELAY_SEC
    try:
        position_manager.broker_service = broker
        position_manager._PARTIAL_CANCEL_POLL_ATTEMPTS = 2
        position_manager._PARTIAL_CANCEL_POLL_DELAY_SEC = 0
        result = position_manager.submit_exit(
            {"symbol": "AAPL", "action": "sell_partial", "qty": 4, "sell_fraction": 0.5}
        )
    finally:
        position_manager.broker_service = old_broker
        position_manager._PARTIAL_CANCEL_POLL_ATTEMPTS = old_attempts
        position_manager._PARTIAL_CANCEL_POLL_DELAY_SEC = old_delay

    assert_equal(result["submitted"], False, "submitted")
    assert_true("did not clear within the poll window" in result["reason"], "reason")
    assert_equal(broker.canceled, ["open-order-1"], "canceled orders")
    assert_equal(broker.submitted, False, "submitted flag")


def test_submit_partial_exit_sells_in_same_pass_once_cancellation_clears():
    """Once canceled brackets clear, the partial sell executes in the same pass."""

    class _Order:
        id = "open-order-1"

    class _SubmittedOrder:
        id = "sell-order-1"
        status = "accepted"

    class _Broker:
        def __init__(self):
            self.canceled = []
            self.submitted_qty = None
            self._open = [_Order()]

        def list_open_orders(self, symbol):
            return list(self._open)

        def cancel_order(self, order_id):
            self.canceled.append(order_id)
            self._open = []  # cancellation settles

        def submit_market_sell(self, symbol, qty):
            self.submitted_qty = qty
            return _SubmittedOrder()

    broker = _Broker()
    old_broker = position_manager.broker_service
    old_delay = position_manager._PARTIAL_CANCEL_POLL_DELAY_SEC
    try:
        position_manager.broker_service = broker
        position_manager._PARTIAL_CANCEL_POLL_DELAY_SEC = 0
        result = position_manager.submit_exit(
            {"symbol": "AAPL", "action": "sell_partial", "qty": 4, "sell_fraction": 0.5}
        )
    finally:
        position_manager.broker_service = old_broker
        position_manager._PARTIAL_CANCEL_POLL_DELAY_SEC = old_delay

    assert_equal(result["submitted"], True, "submitted")
    assert_equal(broker.canceled, ["open-order-1"], "canceled orders")
    assert_equal(broker.submitted_qty, 2, "partial sell qty")
    assert_equal(result["order"]["order_id"], "sell-order-1", "order id")


def test_submit_partial_exit_returns_failure_instead_of_crashing_on_broker_error():
    class _Broker:
        def list_open_orders(self, symbol):
            return []

        def submit_market_sell(self, symbol, qty):
            raise RuntimeError("insufficient qty available for order")

    old_broker = position_manager.broker_service
    try:
        position_manager.broker_service = _Broker()
        result = position_manager.submit_exit(
            {"symbol": "AAPL", "action": "sell_partial", "qty": 4, "sell_fraction": 0.5}
        )
    finally:
        position_manager.broker_service = old_broker

    assert_equal(result["submitted"], False, "submitted")
    assert_true("partial sell submit failed" in result["reason"], "reason")
    assert_true("insufficient qty" in result["reason"], "broker reason")


def main():
    tests = [
        test_continuation_delays_soft_full_exit_when_tape_supports,
        test_continuation_does_not_delay_hard_loss,
        test_partial_exit_promotes_to_full_when_position_is_one_share,
        test_partial_exit_remains_partial_when_share_qty_is_actionable,
        test_weak_entry_peak_lock_tier2_protects_more_profit,
        test_strong_entry_peak_lock_tiers_keep_more_profit,
        test_neutral_and_late_strength_entries_are_weak_context,
        test_strong_conviction_requires_allow_or_boost_setup,
        test_auto_buy_entry_detection_uses_confidence_metadata,
        test_proactive_profit_capture_triggers_while_still_green,
        test_proactive_profit_capture_triggers_faster_for_weak_entries,
        test_proactive_profit_capture_respects_retained_strength_room,
        test_exit_pattern_pressure_triggers_on_green_winner_rollover,
        test_exit_pattern_pressure_gives_retained_strength_extra_confirmation,
        test_exit_pattern_pressure_is_not_armed_before_profit_threshold,
        test_evaluate_position_uses_exit_pattern_pressure_for_partial_profit_capture,
        test_fresh_auto_buy_min_hold_suppresses_soft_peak_lock,
        test_fresh_auto_buy_min_hold_does_not_suppress_severe_loss_exit,
        test_submit_partial_exit_defers_only_when_cancellation_does_not_settle,
        test_submit_partial_exit_sells_in_same_pass_once_cancellation_clears,
        test_submit_partial_exit_returns_failure_instead_of_crashing_on_broker_error,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} position-manager tests passed.")


if __name__ == "__main__":
    main()
