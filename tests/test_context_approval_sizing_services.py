#!/usr/bin/env python3
"""Unit tests for extracted context, approval, and sizing services."""
# ruff: noqa: E402

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.approval_service import _advisory_feature_size_cap, evaluate_approval_decision
from services.context_builder import (
    ContextAssemblyDeps,
    build_final_signal_context,
    build_initial_signal_context,
)
from services.policies import sizing_policy
from services.setup_context_service import SetupContextDeps
from services.signal_models import SignalRuntimeState
from services.sizing_service import (
    apply_final_sizing,
    apply_size_cap,
    build_conviction_stack,
    collect_active_caps,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


@contextmanager
def _temporary_env(**updates):
    original = {key: os.environ.get(key) for key in updates}
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_context_builder_sanitizes_claude_context():
    account_state = {
        "adaptive_buy_confirmation": {"required_buy_confirmations": 3, "reasons": ["test"]},
        "market_alignment": {"aligned_for_buy": True, "reason": "aligned"},
        "setup_observation": {"setup_label": "clean"},
    }
    built = build_final_signal_context(account_state=account_state, trend_table={"AAPL": {}})
    assert_equal(
        "adaptive_buy_confirmation" in built.claude_account_state, False, "adaptive stripped"
    )
    assert_equal("market_alignment" in built.claude_account_state, False, "alignment stripped")
    assert_equal(
        built.claude_account_state["market_context_summary"]["required_confirmations"],
        3,
        "summary confirmations",
    )


def test_context_builder_preserves_caller_claude_state():
    account_state = {
        "symbol": "AAPL",
        "action": "buy",
        "adaptive_buy_confirmation": {"required_buy_confirmations": 2, "reasons": ["test"]},
    }
    built = build_final_signal_context(
        account_state=account_state,
        trend_table={"AAPL": {}},
        claude_account_state={
            "decision_policy": {"decision": "allow"},
            "prior_gate_context": {"source": "final_gate"},
        },
    )

    assert_equal(
        built.claude_account_state["market_context_summary"]["required_confirmations"],
        2,
        "built state preserved",
    )
    assert_equal(
        built.claude_account_state["decision_policy"]["decision"],
        "allow",
        "caller state merged",
    )
    assert_equal(
        built.claude_account_state["prior_gate_context"]["source"],
        "final_gate",
        "caller gate context merged",
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

    class _SetupEngine:
        def classify(self, _snapshot):
            class _Result:
                setup_label = "confirmed_near_vwap_recovery"
                recommendation = "favorable"
                setup_score = 91
                confidence = "medium"
                trend_bucket = "bullish/confirmed"
                vwap_bucket = "near_vwap"
                rs_bucket = "neutral"
                setup_key = "bullish/confirmed|near_vwap|neutral"
                rationale = "engine rationale"
                sample_basis = "test"

            return _Result()

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
                build_snapshot=lambda symbol: {
                    "setup_label": "clean",
                    "id": 42,
                    "base_type": "clean",
                    "prior_failed_breakouts": 0,
                    "compression_ratio": 0.55,
                    "expansion_ratio": 1.45,
                    "distance_to_resistance_pct": 2.1,
                    "reward_risk_ratio": 2.4,
                },
                evaluate_setup_policy=lambda setup_label: {
                    "setup_policy_action": "boost",
                    "reason": "setup_policy:boost",
                },
                upsert_recent_favorable_setup=lambda **kwargs: None,
                get_recent_favorable_setup=lambda **kwargs: {
                    "setup_label": "confirmed_near_vwap_recovery",
                    "setup_policy_action": "boost",
                    "observed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                now=datetime.now,
                recent_favorable_setup_ttl_minutes=15,
                log=_Log(),
                setup_engine=_SetupEngine(),
            ),
            log=_Log(),
            regime_observation_provider=lambda: {
                "regime_observation": {
                    "regime_id": 0,
                    "regime_label": "quiet_bull",
                    "confidence": "medium",
                    "stable": True,
                    "runtime_effect": "observe_only_no_order_authority",
                },
                "regime_routing_decision": {
                    "active_model_slot": "regime_0_model",
                    "sub_model_strategy": "random_forest_trend_continuation",
                    "size_modifier": 1.0,
                    "allow_new_longs": True,
                    "runtime_effect": "observe_only_no_order_authority",
                },
                "regime_observation_source": "test_provider",
            },
        ),
    )

    assert_equal(account_state["execution_mode"], "paper", "execution mode")
    assert_equal(account_state["prior_session"]["session_return_pct"], 3.2, "prior session")
    assert_equal(account_state["tape"]["label"], "clean_momentum", "tape label")
    assert_equal(account_state["tape"]["tape_bar_age_seconds"] is not None, True, "tape age")
    assert_equal(account_state["momentum"]["premarket_bias"], "buy", "momentum bias")
    assert_equal(account_state["premarket_alignment_source"], "live_tape", "alignment source")
    assert_equal(
        account_state["market_regime"]["trend_regime"],
        "mixed",
        "market regime default",
    )
    assert_equal(
        built.market_regime.data["confidence"] in {"very_low", "low", "medium"},
        True,
        "market regime confidence",
    )
    assert_equal(
        account_state["setup_observation"]["setup_label"],
        "confirmed_near_vwap_recovery",
        "setup",
    )
    assert_equal(account_state["setup_quality"]["score"], 91, "setup quality")
    assert_equal(account_state["setup_quality"]["source"], "setup_engine", "setup source")
    assert_equal(account_state["regime_observation"]["regime_label"], "quiet_bull", "regime obs")
    assert_equal(
        account_state["regime_routing_decision"]["active_model_slot"],
        "regime_0_model",
        "regime routing",
    )
    assert_equal(
        account_state["regime_observation_context"]["regime_observation_source"],
        "test_provider",
        "regime source",
    )
    assert_equal(
        account_state["setup_quality"]["structure_state"],
        "high_quality_structure",
        "setup structure",
    )
    assert_equal(
        account_state["recent_favorable_setup"]["setup_label"],
        "confirmed_near_vwap_recovery",
        "recent setup",
    )
    assert_equal(
        built.setup.data["setup_label"],
        "confirmed_near_vwap_recovery",
        "built setup",
    )


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


def test_paper_learning_authority_can_override_claude_low_confidence():
    account_state = {
        "setup_quality": {
            "recommendation": "buy",
            "policy_action": "allow",
            "score": 78,
        },
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 11,
        },
        "prediction_gate": {
            "deterministic_signal_quality_decision": "pass",
        },
        "session_momentum_gate": {"severity": "pass"},
    }
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": False,
            "confidence": "low",
            "reason": "Claude is cautious",
            "position_size_pct": 2.5,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (False, "no override"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config={
            "paper_learning_authority": {
                "enabled": True,
                "min_setup_score": 65,
                "min_buy_opportunity_score": 8,
                "max_position_size_pct": 0.75,
            }
        },
    )

    assert_equal(result.approved, True, "approved")
    assert_equal(result.source, "paper_learning_authority", "source")
    assert_equal(result.category, None, "category")
    assert_equal(result.claude_payload["position_size_pct"], 0.75, "size cap")
    assert_equal(
        account_state["paper_learning_authority_override"]["allowed"],
        True,
        "override marker",
    )


def test_paper_learning_authority_does_not_override_cash_mode():
    account_state = {
        "setup_quality": {
            "recommendation": "buy",
            "policy_action": "allow",
            "score": 90,
        },
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 12,
        },
        "prediction_gate": {
            "deterministic_signal_quality_decision": "pass",
        },
    }
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": False,
            "confidence": "low",
            "reason": "Claude is cautious",
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (False, "no override"),
        tape_exception_enabled=False,
        execution_mode="cash_full",
        ml_authority_config={
            "paper_learning_authority": {
                "enabled": True,
                "min_setup_score": 65,
                "min_buy_opportunity_score": 8,
                "max_position_size_pct": 0.75,
            }
        },
    )

    assert_equal(result.approved, False, "approved")
    assert_equal(result.category, "confidence_gate", "category")
    assert_equal("paper_learning_authority_override" in account_state, False, "override marker")


def test_paper_learning_authority_can_override_claude_unapproved_soft_response():
    account_state = {
        "setup_quality": {
            "recommendation": "buy",
            "policy_action": "allow",
            "score": 82,
        },
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 10,
        },
        "prediction_gate": {
            "deterministic_signal_quality_decision": "pass",
        },
        "session_momentum_gate": {"severity": "pass"},
    }
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": False,
            "confidence": "medium",
            "reason": "mixed context but not an infrastructure failure",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (True, "test override"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config={
            "paper_learning_authority": {
                "enabled": True,
                "min_setup_score": 65,
                "min_buy_opportunity_score": 8,
                "max_position_size_pct": 0.75,
            }
        },
    )

    assert_equal(result.approved, True, "approved")
    assert_equal(result.source, "paper_learning_authority", "source")
    assert_equal(result.claude_payload["position_size_pct"], 0.75, "size cap")


def test_paper_exploration_authority_can_approve_and_increase_size():
    account_state = {
        "setup_quality": {
            "recommendation": "buy",
            "policy_action": "allow",
            "score": 88,
        },
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 13,
        },
        "prediction_gate": {
            "deterministic_signal_quality_decision": "pass",
            "prediction_score": 72,
        },
        "session_momentum_gate": {"severity": "pass"},
        "execution_quality": {"decision": "allow"},
    }
    config = {
        "paper_exploration_authority": {
            "enabled": True,
            "min_setup_score": 78,
            "min_buy_opportunity_score": 10,
            "min_prediction_score": 55,
            "size_lift_multiplier": 1.25,
            "max_position_size_pct": 1.5,
        }
    }
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": False,
            "confidence": "medium",
            "reason": "Claude is cautious despite strong setup",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (True, "test override"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config=config,
    )

    assert_equal(result.approved, True, "approved")
    assert_equal(result.source, "paper_exploration_authority", "source")
    assert_equal(result.claude_payload["position_size_pct"], 1.5, "exploration size cap")
    assert_equal(
        account_state["paper_exploration_authority"]["can_approve_trades"],
        True,
        "can approve trades",
    )

    approved_state = dict(account_state)
    approved_result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": True,
            "confidence": "high",
            "reason": "approved",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=approved_state,
        medium_confidence_override=lambda **_: (True, "test override"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config=config,
    )
    assert_equal(approved_result.approved, True, "approved result")
    assert_equal(approved_result.source, "paper_exploration_authority", "approved source")
    assert_equal(approved_result.claude_payload["position_size_pct"], 1.25, "lifted size")
    assert_equal(
        approved_state["paper_exploration_authority"]["effect"],
        "size_increase",
        "lift effect",
    )


def test_paper_exploration_authority_does_not_run_in_cash_mode():
    account_state = {
        "setup_quality": {"recommendation": "buy", "policy_action": "allow", "score": 95},
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 15,
        },
        "prediction_gate": {
            "deterministic_signal_quality_decision": "pass",
            "prediction_score": 90,
        },
    }
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": True,
            "confidence": "high",
            "reason": "approved",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (True, "test override"),
        tape_exception_enabled=False,
        execution_mode="cash_full",
        ml_authority_config={
            "paper_exploration_authority": {
                "enabled": True,
                "min_setup_score": 78,
                "min_buy_opportunity_score": 10,
                "max_position_size_pct": 1.5,
            }
        },
    )

    assert_equal(result.approved, False, "approved")
    assert_equal(result.source, "authority_matrix", "source")
    assert_equal(result.category, "authority_matrix", "category")
    assert_equal("paper_exploration_authority" in account_state, False, "no paper marker")


def _historical_bar_strategy(**overrides):
    strategy = {
        "status": "paper_ready",
        "master_confidence_score": 78.0,
        "paper_recommendation": "paper_size_candidate",
        "baseline_delta": 7.5,
        "liquidity_stress_bucket": "normal",
        "paper_position_size_pct": 1.4,
    }
    strategy.update(overrides)
    return strategy


def _historical_bar_meta_config(**overrides):
    config = {
        "enabled": True,
        "min_veto_score": 65.0,
        "min_approve_score": 65.0,
        "min_size_increase_score": 75.0,
        "min_baseline_delta": 0.0,
        "max_position_size_pct": 1.5,
        "can_veto": True,
    }
    config.update(overrides)
    return {"historical_bar_meta_label_authority": config}


def _layered_model_config(**overrides):
    config = {"enabled": True}
    config.update(overrides)
    return {
        **_historical_bar_meta_config(),
        "layered_model_authority": config,
    }


def _layered_account_state(**overrides):
    state = {
        "historical_bar_paper_strategy": _historical_bar_strategy(),
        "prediction_gate": {
            "deterministic_signal_quality_decision": "pass",
            "ml_prediction_score": 72.0,
            "prediction_sample_size": 5000,
        },
        "transformer_authority": {
            "enabled": True,
            "decision": "allow",
            "probability": 0.68,
            "status": "paper_gate",
        },
        "regime_routing_decision": {
            "regime_id": 0,
            "regime_label": "quiet_bull",
            "allow_new_longs": True,
            "size_modifier": 1.0,
        },
        "bar_pattern_features": {
            "atr_20_pct": 0.8,
            "vpin_toxicity_20": 0.15,
            "variance_ratio_30m": 1.18,
            "distance_from_vwap_pct": 0.8,
            "vwap_rolling_std_pct": 0.4,
        },
        "execution_quality": {
            "decision": "allow",
            "slippage_estimate_pct": 0.02,
        },
    }
    state.update(overrides)
    return state


def test_layered_model_authority_approves_low_confidence_paper_candidate():
    account_state = _layered_account_state()
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": False,
            "confidence": "low",
            "reason": "Claude did not approve the candidate",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (False, "no override"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config=_layered_model_config(),
    )

    assert_equal(result.approved, True, "approved")
    assert_equal(result.source, "layered_model_authority", "source")
    assert_equal(result.claude_payload["position_size_pct"], 1.4, "size")
    assert_equal(
        account_state["layered_model_decision"]["final_instruction"],
        "paper_approval",
        "layered instruction",
    )
    assert_equal(
        account_state["canonical_decision_trace"]["shadow"]["approval_source"],
        "layered_model_authority",
        "trace source",
    )


def test_layered_model_authority_vetoes_weak_paper_candidate():
    account_state = _layered_account_state(
        historical_bar_paper_strategy=_historical_bar_strategy(
            master_confidence_score=51.0,
            paper_recommendation="paper_avoid",
            paper_position_size_pct=0.0,
        ),
        prediction_gate={"ml_prediction_score": 45.0},
        transformer_authority={"probability": 0.45, "decision": "size_down"},
    )
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": True,
            "confidence": "high",
            "reason": "Claude approves",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (True, "ok"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config=_layered_model_config(),
    )

    assert_equal(result.approved, False, "approved")
    assert_equal(result.source, "layered_model_authority", "source")
    assert_equal(result.category, "layered_model_authority_veto", "category")
    assert_equal(account_state["layered_model_decision"]["final_instruction"], "veto", "final")
    assert_equal(
        account_state["canonical_decision_trace"]["blocking_gate"],
        "ml_authority",
        "blocking gate",
    )


def test_layered_model_authority_cannot_approve_cash_mode():
    account_state = _layered_account_state()
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": True,
            "confidence": "high",
            "reason": "Claude approves",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (True, "ok"),
        tape_exception_enabled=False,
        execution_mode="cash_full",
        ml_authority_config=_layered_model_config(),
    )

    assert_equal(result.approved, False, "approved")
    assert_equal(result.source, "authority_matrix", "source")
    assert_equal("layered_model_decision" in account_state, False, "no layered live authority")


def test_historical_bar_meta_label_authority_approves_low_confidence_paper_candidate():
    account_state = {"historical_bar_paper_strategy": _historical_bar_strategy()}
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": False,
            "confidence": "low",
            "reason": "Layer 1 candidate is uncertain",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (False, "no override"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config=_historical_bar_meta_config(),
    )

    assert_equal(result.approved, True, "approved")
    assert_equal(result.source, "historical_bar_meta_label_authority", "source")
    assert_equal(result.claude_payload["position_size_pct"], 1.4, "size")
    assert_equal(
        account_state["historical_bar_meta_label_authority"]["effect"],
        "paper_approval",
        "effect",
    )


def test_historical_bar_meta_label_authority_increases_size_for_approved_paper_candidate():
    account_state = {"historical_bar_paper_strategy": _historical_bar_strategy()}
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": True,
            "confidence": "high",
            "reason": "Claude approves",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (True, "ok"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config=_historical_bar_meta_config(),
    )

    assert_equal(result.approved, True, "approved")
    assert_equal(result.source, "historical_bar_meta_label_authority", "source")
    assert_equal(result.claude_payload["position_size_pct"], 1.4, "size")
    assert_equal(
        account_state["historical_bar_meta_label_authority"]["effect"],
        "size_increase",
        "effect",
    )


def test_historical_bar_meta_label_authority_vetoes_weak_approved_paper_candidate():
    account_state = {
        "historical_bar_paper_strategy": _historical_bar_strategy(
            master_confidence_score=51.0,
            paper_recommendation="paper_avoid",
            paper_position_size_pct=0.0,
        )
    }
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": True,
            "confidence": "high",
            "reason": "Claude approves",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (True, "ok"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config=_historical_bar_meta_config(),
    )

    assert_equal(result.approved, False, "approved")
    assert_equal(result.source, "historical_bar_meta_label_authority", "source")
    assert_equal(result.category, "historical_bar_meta_label_veto", "category")
    assert_equal(result.claude_payload["position_size_pct"], 0, "size")


def test_approval_service_separates_claude_parse_error_from_confidence_gate():
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": False,
            "confidence": "low",
            "reason": "Parse error - rejecting for safety",
        },
        cash_safe_mode=False,
        market_bias={},
        account_state={},
        medium_confidence_override=lambda **_: (False, "no override"),
        tape_exception_enabled=False,
    )
    assert_equal(result.approved, False, "approved")
    assert_equal(result.category, "claude_parse_error", "category")
    assert_equal(result.source, "claude_parse_error", "source")


def test_approval_service_separates_claude_engine_error_from_confidence_gate():
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": False,
            "confidence": "low",
            "reason": "Engine error: Request timed out or interrupted.",
        },
        cash_safe_mode=False,
        market_bias={},
        account_state={},
        medium_confidence_override=lambda **_: (False, "no override"),
        tape_exception_enabled=False,
    )
    assert_equal(result.approved, False, "approved")
    assert_equal(result.category, "claude_engine_error", "category")
    assert_equal(result.source, "claude_engine_error", "source")


def test_sizing_service_preserves_sell_default_size():
    decision = {"position_size_pct": 0}
    sizing = apply_final_sizing(
        symbol="AAPL",
        action="sell",
        decision=decision,
        risk_multiplier=1.0,
        account_state={},
        apply_buy_opportunity_sizing=lambda **kwargs: (
            kwargs["base_position_size_pct"] * kwargs["risk_multiplier"]
        ),
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


def test_advisory_features_produce_size_cap_and_limiter():
    account_state = {
        "market_microstructure": {
            "breakout_quality": "liquidity_vacuum_breakout",
            "reversion_risk": "high",
        },
        "market_participation": {
            "participation_state": "isolated_or_weak",
            "isolated_move_risk": "high",
        },
        "volatility_normalization": {
            "stretch_state": "extreme_stretch",
            "chase_risk": "high",
        },
        "downside_asymmetry": {
            "downside_state": "asymmetric_downside_high",
            "downside_score": 0.70,
        },
    }

    cap = _advisory_feature_size_cap(account_state)
    account_state["advisory_feature_size_cap"] = cap

    assert_equal(cap["triggered"], True, "triggered")
    assert_equal(cap["source"], "volatility_normalization", "tightest source")
    assert_equal(cap["cap_pct"], 0.6, "cap pct")
    active_caps = collect_active_caps(account_state)
    assert_equal(active_caps[0].source, "advisory_features", "active cap source")


def test_setup_quality_sizing_is_enabled_by_default():
    account_state = {
        "setup_quality": {
            "recommendation": "watch",
            "score": 45,
            "source": "setup_engine",
            "policy_action": "neutral",
        },
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 12,
        },
        "strategy_observation": {"trader_brain": {"score": 80}},
        "session_momentum_gate": {"severity": "pass"},
    }
    with _temporary_env(SETUP_QUALITY_SIZING_ENABLED=None):
        sizing = apply_final_sizing(
            symbol="AAPL",
            action="buy",
            decision={"position_size_pct": 1.0},
            risk_multiplier=1.0,
            account_state=account_state,
            apply_buy_opportunity_sizing=lambda **kwargs: (
                sizing_policy.apply_buy_opportunity_sizing(**kwargs)
            ),
        )

    assert_equal(sizing.final_size_pct, 0.5, "setup quality watch cap")
    assert_equal(account_state["setup_quality_size_cap"]["cap_pct"], 0.5, "setup cap pct")


def test_strong_buy_lift_requires_supportive_setup_quality():
    account_state = {
        "setup_quality": {
            "recommendation": "buy",
            "score": 75,
            "source": "setup_engine",
            "policy_action": "allow",
        },
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 12,
        },
        "strategy_observation": {"trader_brain": {"score": 80}},
        "session_momentum_gate": {"severity": "pass"},
    }
    with _temporary_env(SETUP_QUALITY_SIZING_ENABLED=None):
        sizing = apply_final_sizing(
            symbol="AAPL",
            action="buy",
            decision={"position_size_pct": 1.0},
            risk_multiplier=1.0,
            account_state=account_state,
            apply_buy_opportunity_sizing=lambda **kwargs: (
                sizing_policy.apply_buy_opportunity_sizing(**kwargs)
            ),
        )

    assert_equal(sizing.final_size_pct, 1.1, "supportive setup permits strong buy lift")
    assert_equal("setup_quality_size_cap" in account_state, False, "setup cap absent")


def test_setup_quality_sizing_caps_when_enabled_without_fighting_tighter_caps():
    account_state = {
        "setup_quality": {
            "recommendation": "watch",
            "score": 45,
            "source": "setup_engine",
            "policy_action": "neutral",
        },
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 12,
        },
        "strategy_observation": {"trader_brain": {"score": 80}},
        "session_momentum_gate": {"severity": "pass"},
    }
    with _temporary_env(SETUP_QUALITY_SIZING_ENABLED="true"):
        sizing = apply_final_sizing(
            symbol="AAPL",
            action="buy",
            decision={"position_size_pct": 1.0},
            risk_multiplier=1.0,
            account_state=account_state,
            apply_buy_opportunity_sizing=lambda **kwargs: (
                sizing_policy.apply_buy_opportunity_sizing(**kwargs)
            ),
        )

    assert_equal(sizing.final_size_pct, 0.5, "setup quality watch cap")
    assert_equal(account_state["setup_quality_size_cap"]["cap_pct"], 0.5, "setup cap pct")
    assert_equal(sizing.dominant_limiter, "setup_quality", "setup limiter")

    account_state = {
        "max_position_size_pct_override": 0.5,
        "dominant_limiter": "weak_prediction_degraded",
        "weak_prediction_setup_gate": {"triggered": True},
        "setup_quality": {
            "recommendation": "watch",
            "score": 45,
            "source": "setup_engine",
            "policy_action": "neutral",
        },
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 12,
        },
    }
    with _temporary_env(SETUP_QUALITY_SIZING_ENABLED="true"):
        sizing = apply_final_sizing(
            symbol="AAPL",
            action="buy",
            decision={"position_size_pct": 1.0},
            risk_multiplier=1.0,
            account_state=account_state,
            apply_buy_opportunity_sizing=lambda **kwargs: (
                sizing_policy.apply_buy_opportunity_sizing(**kwargs)
            ),
        )

    assert_equal(sizing.final_size_pct, 0.5, "tighter weak-prediction cap wins")
    assert_equal(sizing.dominant_limiter, "weak_prediction_degraded", "tighter limiter")


def test_slippage_kelly_sizing_can_zero_high_friction_buy():
    account_state = {
        "prediction_gate": {"ml_prediction_score": 0.72},
        "atr_20_pct": 1.0,
        "execution_quality": {"slippage_estimate_pct": 0.25},
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 12,
        },
    }
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_MAX_FRICTION_RATIO="0.20",
    ):
        sizing = apply_final_sizing(
            symbol="AAPL",
            action="buy",
            decision={"position_size_pct": 1.0},
            risk_multiplier=1.0,
            account_state=account_state,
            apply_buy_opportunity_sizing=lambda **kwargs: (
                sizing_policy.apply_buy_opportunity_sizing(**kwargs)
            ),
        )

    assert_equal(sizing.final_size_pct, 0.0, "slippage Kelly zero cap")
    assert_equal(sizing.dominant_limiter, "slippage_kelly", "slippage limiter")
    assert_equal(
        account_state["slippage_kelly_sizing"]["runtime_effect"],
        "size_cap_only_no_approval_authority",
        "runtime effect",
    )


def main():
    tests = [
        test_context_builder_sanitizes_claude_context,
        test_initial_context_builder_hydrates_buy_context,
        test_approval_service_converts_low_confidence_to_category,
        test_paper_learning_authority_can_override_claude_low_confidence,
        test_paper_learning_authority_does_not_override_cash_mode,
        test_paper_learning_authority_can_override_claude_unapproved_soft_response,
        test_paper_exploration_authority_can_approve_and_increase_size,
        test_paper_exploration_authority_does_not_run_in_cash_mode,
        test_layered_model_authority_approves_low_confidence_paper_candidate,
        test_layered_model_authority_vetoes_weak_paper_candidate,
        test_layered_model_authority_cannot_approve_cash_mode,
        test_historical_bar_meta_label_authority_approves_low_confidence_paper_candidate,
        test_historical_bar_meta_label_authority_increases_size_for_approved_paper_candidate,
        test_historical_bar_meta_label_authority_vetoes_weak_approved_paper_candidate,
        test_approval_service_separates_claude_parse_error_from_confidence_gate,
        test_approval_service_separates_claude_engine_error_from_confidence_gate,
        test_sizing_service_preserves_sell_default_size,
        test_apply_size_cap_keeps_tightest_cap,
        test_conviction_stack_sets_dominant_limiter,
        test_advisory_features_produce_size_cap_and_limiter,
        test_setup_quality_sizing_is_enabled_by_default,
        test_strong_buy_lift_requires_supportive_setup_quality,
        test_setup_quality_sizing_caps_when_enabled_without_fighting_tighter_caps,
        test_slippage_kelly_sizing_can_zero_high_friction_buy,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} context/approval/sizing service tests passed.")


if __name__ == "__main__":
    main()
