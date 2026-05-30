#!/usr/bin/env python3
"""Unit tests for extracted context, approval, and sizing services."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.approval_service import evaluate_approval_decision
from services.context_builder import (
    ContextAssemblyDeps,
    build_final_signal_context,
    build_initial_signal_context,
)
from services.setup_context_service import SetupContextDeps
from services.signal_models import SignalRuntimeState
from services.sizing_service import apply_final_sizing, apply_size_cap, build_conviction_stack


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_context_builder_sanitizes_claude_context():
    account_state = {
        "adaptive_buy_confirmation": {"required_buy_confirmations": 3, "reasons": ["test"]},
        "market_alignment": {"aligned_for_buy": True, "reason": "aligned"},
        "setup_observation": {"setup_label": "clean"},
    }
    built = build_final_signal_context(account_state=account_state, trend_table={"AAPL": {}})
    assert_equal("adaptive_buy_confirmation" in built.claude_account_state, False, "adaptive stripped")
    assert_equal("market_alignment" in built.claude_account_state, False, "alignment stripped")
    assert_equal(
        built.claude_account_state["market_context_summary"]["required_confirmations"],
        3,
        "summary confirmations",
    )


def test_initial_context_builder_hydrates_buy_context():
    account_state = {}
    state = SignalRuntimeState(
        raw_signal={"symbol": "AAPL", "action": "buy", "price": 325.0},
        symbol="AAPL",
        action="buy",
        received_at=datetime.now(timezone.utc),
        account_state=account_state,
    )

    class _Log:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

    built = build_initial_signal_context(
        state,
        ContextAssemblyDeps(
            execution_mode="paper",
            market_bias={"AAPL": {"bias": "buy"}},
            trend_table={"AAPL": {"direction": "bullish"}},
            rolling_symbol_context=lambda symbol: {"symbol": symbol, "special_labels": ["x"]},
            prior_session_context=lambda symbol: {"symbol": symbol, "session_return_pct": 3.2},
            build_tape_context=lambda symbol, current_price: {
                "classification": {"label": "clean_momentum"},
                "state": {"latest_bar_timestamp": datetime.now(timezone.utc).isoformat()},
                "ok": True,
                "bar_count": 12,
            },
            get_momentum=lambda symbol, price, premarket_bias=None: {
                "direction": "rising",
                "momentum_pct": 0.2,
                "premarket_bias": premarket_bias,
            },
            setup_context_deps=SetupContextDeps(
                build_snapshot=lambda symbol: {"setup_label": "clean"},
                evaluate_setup_policy=lambda setup_label: {
                    "setup_policy_action": "boost",
                    "reason": "setup_policy:boost",
                },
                upsert_recent_favorable_setup=lambda **kwargs: None,
                get_recent_favorable_setup=lambda **kwargs: {
                    "setup_label": "clean",
                    "setup_policy_action": "boost",
                    "observed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                now=datetime.now,
                recent_favorable_setup_ttl_minutes=15,
                log=_Log(),
            ),
            log=_Log(),
        ),
    )

    assert_equal(account_state["execution_mode"], "paper", "execution mode")
    assert_equal(account_state["prior_session"]["session_return_pct"], 3.2, "prior session")
    assert_equal(account_state["tape"]["label"], "clean_momentum", "tape label")
    assert_equal(account_state["tape"]["tape_bar_age_seconds"] is not None, True, "tape age")
    assert_equal(account_state["momentum"]["premarket_bias"], "buy", "momentum bias")
    assert_equal(account_state["premarket_alignment_source"], "live_tape", "alignment source")
    assert_equal(account_state["setup_observation"]["setup_label"], "clean", "setup")
    assert_equal(account_state["recent_favorable_setup"]["setup_label"], "clean", "recent setup")
    assert_equal(built.setup.data["setup_label"], "clean", "built setup")


def test_approval_service_converts_low_confidence_to_category():
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": True,
            "confidence": "low",
            "reason": "too weak",
        },
        cash_safe_mode=False,
        market_bias={},
        account_state={},
        medium_confidence_override=lambda **_: (False, "no override"),
        tape_exception_enabled=False,
    )
    assert_equal(result.approved, False, "approved")
    assert_equal(result.category, "confidence_gate", "category")


def test_sizing_service_preserves_legacy_sell_default_size():
    decision = {"position_size_pct": 0}
    sizing = apply_final_sizing(
        symbol="AAPL",
        action="sell",
        decision=decision,
        risk_multiplier=1.0,
        account_state={},
        apply_buy_opportunity_sizing=lambda **kwargs: kwargs["base_position_size_pct"]
        * kwargs["risk_multiplier"],
    )
    assert_equal(sizing.final_size_pct, 1.0, "sell default size")


def test_apply_size_cap_keeps_tightest_cap():
    state = {"max_position_size_pct_override": 0.75}
    applied = apply_size_cap(
        state,
        cap_pct=0.5,
        state_key="weak_prediction_setup_gate",
        payload={"triggered": True},
    )
    assert_equal(applied, 0.5, "applied cap")
    assert_equal(state["weak_prediction_setup_gate"]["triggered"], True, "payload")


def test_conviction_stack_sets_dominant_limiter():
    account_state = {
        "weak_prediction_setup_gate": {"triggered": True},
        "buy_opportunity": {"buy_opportunity_recommendation": "watch"},
        "strategy_observation": {"trader_brain": {"score": 30}},
    }
    stack = build_conviction_stack(
        action="buy",
        account_state=account_state,
        ml_prediction_bucket=lambda raw: "weak_below_45",
        compute_dominant_limiter=lambda state: "weak_prediction_degraded",
    )
    assert_equal(stack["buy_opportunity"], "watch", "buy opportunity")
    assert_equal(account_state["dominant_limiter"], "weak_prediction_degraded", "limiter")


def main():
    tests = [
        test_context_builder_sanitizes_claude_context,
        test_initial_context_builder_hydrates_buy_context,
        test_approval_service_converts_low_confidence_to_category,
        test_sizing_service_preserves_legacy_sell_default_size,
        test_apply_size_cap_keeps_tightest_cap,
        test_conviction_stack_sets_dominant_limiter,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} context/approval/sizing service tests passed.")


if __name__ == "__main__":
    main()
