"""
Focused tests for internal auto-buy candidate scoring.

Run:
  python3 tests/test_auto_buy_manager.py
"""
# ruff: noqa: E402, I001

import json
import sys
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auto_buy_manager import attach_canonical_decision_metadata
from auto_buy_manager import evaluate_auto_buy_candidate
from auto_buy_manager import auto_buy_capacity_check
from auto_buy_manager import log_auto_buy_order
from auto_buy_manager import maybe_execute_auto_buy
from auto_buy_manager import should_collect_candidates
import auto_buy_manager


AUTO_BUY_RUNTIME_DEFAULTS = {
    "AUTO_BUY_SIGNAL_MODE": "legacy_source_gate",
    "TRADINGVIEW_ALERTS_DEPRECATED": False,
    "AUTO_BUY_ALLOW_TRADINGVIEW_LIVE": False,
    "AUTO_BUY_LIVE_BUYS": False,
    "AUTO_BUY_LEARNED_TIEBREAKER_ENABLED": False,
    "AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED": False,
    "AUTO_BUY_INTRADAY_FEEDBACK_ENABLED": False,
    "AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED": False,
    "AUTO_BUY_LAYERED_ML_ENABLED": False,
    "AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED": False,
    "AUTO_BUY_LAYERED_ML_VETO_HARD_BLOCK_ENABLED": False,
}


def reset_auto_buy_runtime_defaults():
    for key, value in AUTO_BUY_RUNTIME_DEFAULTS.items():
        setattr(auto_buy_manager, key, value)
    auto_buy_manager._rolling_momentum_context_cache = None
    auto_buy_manager._historical_bar_intelligence_cache = None


def setup_function(_):
    reset_auto_buy_runtime_defaults()
    auto_buy_manager.memory_for_signal = lambda symbol, context: {"available": False}
    auto_buy_manager.auto_buy_prediction_context = lambda symbol: {
        "available": True,
        "ml_prediction_score": 58.0,
        "ml_prediction_bucket": "high_55_plus",
        "ml_prediction_sample_size": 100,
    }


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def strong_session():
    return {
        "trend_label": "strong_uptrend",
        "trend_score": 7,
        "session_return_pct": 1.2,
        "momentum_5m_pct": 0.2,
        "momentum_15m_pct": 0.45,
        "momentum_30m_pct": 0.65,
        "distance_from_vwap_pct": 0.4,
    }


def favorable_feature():
    return {
        "id": 123,
        "setup_label": "near_vwap_weak_strength_followthrough",
        "setup_recommendation": "favorable",
        "setup_score": 88,
        "relative_strength_5m": 0.4,
        "ret_5m": 0.2,
        "ret_15m": 0.3,
        "distance_from_vwap": 0.2,
    }


def buy_context():
    return {
        "bias": "buy",
        "entry_quality": "good_if_holds_gap",
        "risk_level": "medium",
        "avoid_type": None,
    }


def test_strong_internal_candidate_scores_as_buy_candidate():
    result = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=strong_session(),
        feature=favorable_feature(),
        context=buy_context(),
        held=set(),
    )

    assert_equal(result["decision"], "strong_buy_candidate", "decision")
    assert_equal(result["severity"], "high", "severity")
    assert_equal(
        result["pattern_runtime_effect"],
        "observe_only_no_live_authority",
        "pattern runtime effect",
    )
    if not result.get("symbol_pattern"):
        raise AssertionError("missing symbol pattern")


def test_five_day_rolling_context_is_scored_and_returned():
    result = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=strong_session(),
        feature=favorable_feature(),
        context=buy_context(),
        rolling_context={
            "five_day_return_pct": 3.2,
            "prior_day_return_pct": 0.8,
            "current_price_vs_prior_close_pct": 1.1,
            "extension_from_recent_base_pct": 2.4,
            "continuation_score": 4,
            "trend_context": "strong_continuation",
            "generated_at": "2026-06-04T09:45:00",
            "latest_bar_time_et": "2026-06-04T09:44:00-04:00",
            "data_feed": "iex",
            "market_days_found": 8,
            "last_5_market_days": [
                "2026-05-28",
                "2026-05-29",
                "2026-06-01",
                "2026-06-02",
                "2026-06-03",
            ],
        },
        held=set(),
    )

    assert_equal(result["five_day_return_pct"], 3.2, "five day return")
    assert_equal(result["rolling_continuation_score"], 4.0, "rolling score")
    assert_equal(result["rolling_trend_context"], "strong_continuation", "rolling trend")
    assert_equal(result["rolling_momentum_source"], "rolling_momentum_json", "rolling source")
    if "5d_trend_aligned" not in result["reason"]:
        raise AssertionError("5-day alignment was not included in scoring reason")


def test_held_symbol_is_skipped():
    result = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=strong_session(),
        feature=favorable_feature(),
        context=buy_context(),
        held={"AMZN"},
    )

    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["severity"], "held", "severity")


def test_negative_session_blocks_candidate():
    session = strong_session()
    session["trend_label"] = "downtrend"
    session["trend_score"] = -6
    session["momentum_15m_pct"] = -0.5

    result = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=session,
        feature=favorable_feature(),
        context=buy_context(),
        held=set(),
    )

    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["severity"], "blocked", "severity")
    if "negative_session:downtrend" not in result["hard_block_reason"]:
        raise AssertionError(f"missing hard block reason: {result['hard_block_reason']}")


def test_weak_ml_prediction_blocks_auto_buy_candidate():
    old_prediction_context = auto_buy_manager.auto_buy_prediction_context
    auto_buy_manager.auto_buy_prediction_context = lambda symbol: {
        "available": True,
        "prediction_score": 41.0,
        "prediction_decision": "observe_only",
        "prediction_reason": "test weak prediction",
        "ml_prediction_score": 41.0,
        "ml_prediction_bucket": "weak_below_45",
        "ml_prediction_confidence": "medium",
        "ml_prediction_sample_size": 30,
    }
    try:
        result = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=strong_session(),
            feature=favorable_feature(),
            context=buy_context(),
            held=set(),
        )
    finally:
        auto_buy_manager.auto_buy_prediction_context = old_prediction_context

    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["severity"], "blocked", "severity")
    assert_equal(result["ml_prediction_bucket"], "weak_below_45", "bucket")
    if "ml_prediction_weak" not in result["hard_block_reason"]:
        raise AssertionError(f"missing ML weak block: {result['hard_block_reason']}")


def test_weak_ml_bucket_blocks_even_with_thin_sample():
    old_prediction_context = auto_buy_manager.auto_buy_prediction_context
    auto_buy_manager.auto_buy_prediction_context = lambda symbol: {
        "available": True,
        "prediction_score": 43.0,
        "prediction_decision": "observe_only",
        "prediction_reason": "test weak bucket",
        "ml_prediction_score": 43.0,
        "ml_prediction_bucket": "weak_below_45",
        "ml_prediction_confidence": "very_low",
        "ml_prediction_sample_size": 0,
    }
    try:
        result = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=strong_session(),
            feature=favorable_feature(),
            context=buy_context(),
            held=set(),
        )
    finally:
        auto_buy_manager.auto_buy_prediction_context = old_prediction_context

    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["severity"], "blocked", "severity")
    if "ml_prediction_weak_bucket" not in result["hard_block_reason"]:
        raise AssertionError(f"missing ML weak bucket block: {result['hard_block_reason']}")


def test_intraday_feedback_blocks_repeated_losing_pattern():
    old_prediction_context = auto_buy_manager.auto_buy_prediction_context
    old_cash_mode = auto_buy_manager.is_cash_mode
    old_enabled = auto_buy_manager.AUTO_BUY_INTRADAY_FEEDBACK_ENABLED
    auto_buy_manager.auto_buy_prediction_context = lambda symbol: {
        "available": True,
        "prediction_score": 44.0,
        "prediction_decision": "observe_only",
        "prediction_reason": "test weak bucket",
        "ml_prediction_score": 44.0,
        "ml_prediction_bucket": "weak_below_45",
        "ml_prediction_confidence": "medium",
        "ml_prediction_sample_size": 30,
    }
    auto_buy_manager.is_cash_mode = lambda: False
    auto_buy_manager.AUTO_BUY_INTRADAY_FEEDBACK_ENABLED = True
    feature = favorable_feature()
    feature["setup_recommendation"] = "avoid"
    feature["setup_label"] = "near_vwap_neutral_fade_risk"
    feature["setup_score"] = 45
    try:
        result = evaluate_auto_buy_candidate(
            symbol="AAPL",
            session=strong_session(),
            feature=feature,
            context=buy_context(),
            intraday_feedback_evidence={
                "ml=weak_below_45|setup_action=avoid": {
                    "key": "ml=weak_below_45|setup_action=avoid",
                    "trades": 3,
                    "wins": 0,
                    "losses": 3,
                    "loss_rate": 1.0,
                    "avg_pnl_pct": -0.35,
                    "symbols": ["AAPL"],
                }
            },
            held=set(),
        )
    finally:
        auto_buy_manager.auto_buy_prediction_context = old_prediction_context
        auto_buy_manager.is_cash_mode = old_cash_mode
        auto_buy_manager.AUTO_BUY_INTRADAY_FEEDBACK_ENABLED = old_enabled

    assert_equal(result["decision"], "skip", "feedback decision")
    assert_equal(result["intraday_feedback_status"], "block", "feedback status")
    if "intraday_pattern_feedback" not in result["hard_block_reason"]:
        raise AssertionError(f"missing intraday feedback hard block: {result['hard_block_reason']}")


def test_paper_strong_evidence_promotes_setup_soft_block_only():
    old_cash_mode = auto_buy_manager.is_cash_mode
    old_promotion = auto_buy_manager.AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED
    old_watch = auto_buy_manager.AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED
    old_prediction_context = auto_buy_manager.auto_buy_prediction_context
    auto_buy_manager.is_cash_mode = lambda: False
    auto_buy_manager.AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED = True
    auto_buy_manager.AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED = True
    auto_buy_manager.auto_buy_prediction_context = lambda symbol: {
        "available": True,
        "ml_prediction_score": 54.0,
        "ml_prediction_bucket": "mid_50_55",
        "ml_prediction_sample_size": 30,
    }
    session = strong_session()
    session["trend_score"] = 8
    session["session_return_pct"] = 1.1
    session["momentum_15m_pct"] = 0.35
    session["momentum_30m_pct"] = 0.55
    feature = favorable_feature()
    feature["setup_recommendation"] = "avoid"
    feature["setup_label"] = "near_vwap_neutral_fade_risk"
    feature["setup_score"] = 62
    try:
        result = evaluate_auto_buy_candidate(
            symbol="SOFI",
            session=session,
            feature=feature,
            context=buy_context(),
            rolling_context={
                "five_day_return_pct": 4.2,
                "continuation_score": 5,
                "trend_context": "strong_continuation",
            },
            held=set(),
        )
    finally:
        auto_buy_manager.is_cash_mode = old_cash_mode
        auto_buy_manager.AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED = old_promotion
        auto_buy_manager.AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED = old_watch
        auto_buy_manager.auto_buy_prediction_context = old_prediction_context

    assert_equal(result["decision"], "strong_buy_candidate", "decision")
    assert_equal(result["paper_strong_evidence_promotion_applied"], True, "promotion applied")
    assert_equal(result["hard_block_reason"], None, "soft block cleared")
    if "paper_strong_evidence_promoted" not in result["reason"]:
        raise AssertionError(f"missing paper promotion reason: {result['reason']}")


def test_paper_strong_evidence_does_not_promote_weak_ml_block():
    old_cash_mode = auto_buy_manager.is_cash_mode
    old_promotion = auto_buy_manager.AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED
    old_prediction_context = auto_buy_manager.auto_buy_prediction_context
    auto_buy_manager.is_cash_mode = lambda: False
    auto_buy_manager.AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED = True
    auto_buy_manager.auto_buy_prediction_context = lambda symbol: {
        "available": True,
        "ml_prediction_score": 41.0,
        "ml_prediction_bucket": "weak_below_45",
        "ml_prediction_sample_size": 30,
    }
    try:
        result = evaluate_auto_buy_candidate(
            symbol="SOFI",
            session=strong_session(),
            feature=favorable_feature(),
            context=buy_context(),
            held=set(),
        )
    finally:
        auto_buy_manager.is_cash_mode = old_cash_mode
        auto_buy_manager.AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED = old_promotion
        auto_buy_manager.auto_buy_prediction_context = old_prediction_context

    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["paper_strong_evidence_promotion_applied"], False, "promotion applied")
    if "ml_prediction_weak" not in result["hard_block_reason"]:
        raise AssertionError(f"missing weak ML block: {result['hard_block_reason']}")


def test_watch_setup_cannot_become_strong_buy_by_default():
    feature = favorable_feature()
    feature["setup_recommendation"] = "watch"
    feature["setup_score"] = 95
    old_prediction_context = auto_buy_manager.auto_buy_prediction_context
    auto_buy_manager.auto_buy_prediction_context = lambda symbol: {
        "available": True,
        "ml_prediction_score": 58.0,
        "ml_prediction_bucket": "high_55_plus",
        "ml_prediction_sample_size": 100,
    }
    try:
        result = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=strong_session(),
            feature=feature,
            context=buy_context(),
            held=set(),
        )
    finally:
        auto_buy_manager.auto_buy_prediction_context = old_prediction_context

    assert_equal(result["decision"], "watch", "decision")
    assert_equal(result["severity"], "medium", "severity")


def test_early_constructive_build_gets_buy_candidate_boost():
    session = strong_session()
    session["trend_label"] = "developing_uptrend"
    session["trend_score"] = 4
    session["session_return_pct"] = 0.42
    session["momentum_5m_pct"] = 0.08
    session["momentum_15m_pct"] = 0.18
    session["momentum_30m_pct"] = 0.12
    session["distance_from_vwap_pct"] = 0.32
    feature = favorable_feature()
    feature["setup_recommendation"] = "watch"
    feature["setup_score"] = 56

    result = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=session,
        feature=feature,
        context=buy_context(),
        held=set(),
    )

    assert_equal(result["early_constructive_build"], True, "early build flag")
    if "early_constructive_build:+3" not in result["reason"]:
        raise AssertionError(f"missing early build reason: {result['reason']}")
    assert_equal(result["decision"], "watch", "watch setup still capped")


def test_mature_chase_extension_is_penalized_and_extreme_chase_blocks():
    session = strong_session()
    session["session_return_pct"] = 3.1
    session["distance_from_vwap_pct"] = 1.42
    feature = favorable_feature()
    feature["setup_label"] = "above_vwap_strength_continuation"
    feature["setup_recommendation"] = "favorable"
    feature["setup_score"] = 82

    result = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=session,
        feature=feature,
        context=buy_context(),
        held=set(),
    )

    assert_equal(result["mature_chase"], True, "mature chase flag")
    assert_equal(result["extreme_chase"], True, "extreme chase flag")
    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["severity"], "blocked", "severity")
    if "mature_chase_extension:-4" not in result["reason"]:
        raise AssertionError(f"missing mature chase reason: {result['reason']}")
    if "extreme_mature_chase" not in result["hard_block_reason"]:
        raise AssertionError(f"missing extreme chase block: {result['hard_block_reason']}")


def test_unclassified_extended_vwap_blocks_candidate():
    session = strong_session()
    session["distance_from_vwap_pct"] = 1.65
    feature = favorable_feature()
    feature["setup_label"] = "unclassified_transition"
    feature["setup_recommendation"] = "watch"
    feature["setup_score"] = 35

    result = evaluate_auto_buy_candidate(
        symbol="VRT",
        session=session,
        feature=feature,
        context=buy_context(),
        held=set(),
    )

    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["severity"], "blocked", "severity")
    if "unclassified_extended_vwap" not in result["hard_block_reason"]:
        raise AssertionError(f"missing unclassified vwap block: {result['hard_block_reason']}")


def test_strategy_memory_caution_reduces_auto_buy_score():
    old_memory = auto_buy_manager.memory_for_signal
    auto_buy_manager.memory_for_signal = lambda symbol, context: {
        "available": True,
        "recommendation": "caution",
        "min_setup_score": 95,
        "reason": "historical weak setup outcome",
        "symbol_memory": {"trades": 6},
    }
    try:
        result = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=strong_session(),
            feature=favorable_feature(),
            context=buy_context(),
            held=set(),
        )
    finally:
        auto_buy_manager.memory_for_signal = old_memory

    assert_equal(result["strategy_memory_recommendation"], "caution", "memory rec")
    assert_equal(result["decision"], "watch", "decision")
    if "strategy_memory_caution_setup_below_min" not in result["reason"]:
        raise AssertionError(f"missing strategy memory caution reason: {result['reason']}")
    if "strategy_memory_caution_caps_at_watch" not in result["reason"]:
        raise AssertionError(f"missing strategy memory watch cap: {result['reason']}")


def test_strategy_memory_avoid_blocks_auto_buy_candidate():
    old_memory = auto_buy_manager.memory_for_signal
    auto_buy_manager.memory_for_signal = lambda symbol, context: {
        "available": True,
        "recommendation": "avoid",
        "min_setup_score": 95,
        "reason": "recent avoid lesson",
        "symbol_memory": {"trades": 8},
    }
    try:
        result = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=strong_session(),
            feature=favorable_feature(),
            context=buy_context(),
            held=set(),
        )
    finally:
        auto_buy_manager.memory_for_signal = old_memory

    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["severity"], "blocked", "severity")
    if "strategy_memory_avoid" not in result["hard_block_reason"]:
        raise AssertionError(f"missing strategy memory block: {result['hard_block_reason']}")


def test_tradingview_symbols_need_higher_auto_buy_threshold():
    # This test requires legacy_source_gate so the webhook threshold penalty applies.
    # The live env may have internal_all which disables the penalty.
    reset_auto_buy_runtime_defaults()

    session = strong_session()
    session["trend_label"] = "developing_uptrend"
    session["trend_score"] = 3
    session["momentum_5m_pct"] = 0.0
    session["momentum_15m_pct"] = 0.0
    session["momentum_30m_pct"] = 0.0

    internal = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=session,
        feature=favorable_feature(),
        context=buy_context(),
        held=set(),
        signal_source="internal_bar_only",
    )
    webhook_symbol = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=session,
        feature=favorable_feature(),
        context=buy_context(),
        held=set(),
        signal_source="tradingview_alert",
    )

    assert_equal(internal["decision"], "strong_buy_candidate", "internal decision")
    assert_equal(webhook_symbol["decision"], "watch", "webhook-symbol decision")
    assert_equal(
        webhook_symbol["strong_buy_threshold"],
        auto_buy_manager.AUTO_BUY_MIN_SCORE + 4.0,
        "threshold",
    )
    assert_equal(webhook_symbol["requires_tradingview_webhook"], True, "requires webhook")


def test_internal_all_mode_removes_tradingview_threshold_penalty():
    old_mode = auto_buy_manager.AUTO_BUY_SIGNAL_MODE
    old_deprecated = auto_buy_manager.TRADINGVIEW_ALERTS_DEPRECATED
    old_allow = auto_buy_manager.AUTO_BUY_ALLOW_TRADINGVIEW_LIVE
    auto_buy_manager.AUTO_BUY_SIGNAL_MODE = "internal_all"
    auto_buy_manager.TRADINGVIEW_ALERTS_DEPRECATED = False
    auto_buy_manager.AUTO_BUY_ALLOW_TRADINGVIEW_LIVE = False
    try:
        session = strong_session()
        session["trend_label"] = "developing_uptrend"
        session["trend_score"] = 3
        session["momentum_5m_pct"] = 0.0
        session["momentum_15m_pct"] = 0.0
        session["momentum_30m_pct"] = 0.0

        result = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=session,
            feature=favorable_feature(),
            context=buy_context(),
            held=set(),
            signal_source="tradingview_alert",
        )
    finally:
        auto_buy_manager.AUTO_BUY_SIGNAL_MODE = old_mode
        auto_buy_manager.TRADINGVIEW_ALERTS_DEPRECATED = old_deprecated
        auto_buy_manager.AUTO_BUY_ALLOW_TRADINGVIEW_LIVE = old_allow

    assert_equal(result["decision"], "strong_buy_candidate", "decision")
    assert_equal(result["strong_buy_threshold"], auto_buy_manager.AUTO_BUY_MIN_SCORE, "threshold")
    assert_equal(result["requires_tradingview_webhook"], False, "requires webhook")
    assert_equal(result["execution_signal_mode"], "internal_all", "signal mode")


def test_early_session_buffer_skips_collection():
    import pytz
    from datetime import datetime

    et = pytz.timezone("America/New_York")
    ok, reason = should_collect_candidates(et.localize(datetime(2026, 5, 26, 9, 35)))

    assert_equal(ok, False, "collection allowed")
    if "session elapsed" not in reason:
        raise AssertionError(f"unexpected buffer reason: {reason}")


def test_live_buy_requires_market_open_and_env_flag():
    candidate = {
        "symbol": "AMZN",
        "decision": "strong_buy_candidate",
        "risk_level": "medium",
    }

    order = maybe_execute_auto_buy(candidate, market_open=False, live_requested=False)

    assert_equal(order, None, "order")
    assert_equal(
        candidate["live_block_reason"],
        "auto-buy is candidate discovery only; execution delegated to canonical signal path",
        "block reason",
    )
    assert_equal(
        candidate["auto_buy_runtime_effect"],
        "candidate_discovery_only_no_order_routing",
        "runtime effect",
    )


def test_live_auto_buy_does_not_execute_tradingview_alert_symbols_by_default():
    old_live = auto_buy_manager.AUTO_BUY_LIVE_BUYS
    old_allow = auto_buy_manager.AUTO_BUY_ALLOW_TRADINGVIEW_LIVE
    auto_buy_manager.AUTO_BUY_LIVE_BUYS = True
    auto_buy_manager.AUTO_BUY_ALLOW_TRADINGVIEW_LIVE = False
    try:
        candidate = {
            "symbol": "AMZN",
            "decision": "strong_buy_candidate",
            "signal_source": "tradingview_alert",
            "risk_level": "medium",
        }

        order = maybe_execute_auto_buy(candidate, market_open=True, live_requested=True)
    finally:
        auto_buy_manager.AUTO_BUY_LIVE_BUYS = old_live
        auto_buy_manager.AUTO_BUY_ALLOW_TRADINGVIEW_LIVE = old_allow

    assert_equal(order, None, "order")
    assert_equal(
        candidate["live_block_reason"],
        "auto-buy is candidate discovery only; execution delegated to canonical signal path",
        "block reason",
    )


def test_internal_all_mode_stays_candidate_only_for_tradingview_symbols():
    old_live = auto_buy_manager.AUTO_BUY_LIVE_BUYS
    old_allow = auto_buy_manager.AUTO_BUY_ALLOW_TRADINGVIEW_LIVE
    old_mode = auto_buy_manager.AUTO_BUY_SIGNAL_MODE
    old_deprecated = auto_buy_manager.TRADINGVIEW_ALERTS_DEPRECATED
    old_capacity = auto_buy_manager.auto_buy_capacity_check
    auto_buy_manager.AUTO_BUY_LIVE_BUYS = True
    auto_buy_manager.AUTO_BUY_ALLOW_TRADINGVIEW_LIVE = False
    auto_buy_manager.AUTO_BUY_SIGNAL_MODE = "internal_all"
    auto_buy_manager.TRADINGVIEW_ALERTS_DEPRECATED = False
    auto_buy_manager.auto_buy_capacity_check = lambda: (False, "capacity stopped")
    try:
        candidate = {
            "symbol": "AMZN",
            "decision": "strong_buy_candidate",
            "signal_source": "tradingview_alert",
            "risk_level": "medium",
        }

        order = maybe_execute_auto_buy(candidate, market_open=True, live_requested=True)
    finally:
        auto_buy_manager.AUTO_BUY_LIVE_BUYS = old_live
        auto_buy_manager.AUTO_BUY_ALLOW_TRADINGVIEW_LIVE = old_allow
        auto_buy_manager.AUTO_BUY_SIGNAL_MODE = old_mode
        auto_buy_manager.TRADINGVIEW_ALERTS_DEPRECATED = old_deprecated
        auto_buy_manager.auto_buy_capacity_check = old_capacity

    assert_equal(order, None, "order")
    assert_equal(
        candidate["live_block_reason"],
        "auto-buy is candidate discovery only; execution delegated to canonical signal path",
        "block reason",
    )


def test_cash_safe_daily_symbol_cap_only_applies_in_cash_modes():
    old_is_cash_mode = auto_buy_manager.is_cash_mode
    old_buys_today = auto_buy_manager.app_approved_buys_today
    old_buy_cooldown = auto_buy_manager.app_buy_cooldown_active
    old_recent_sell = auto_buy_manager.recent_sell_active
    old_positions = auto_buy_manager.broker_positions_and_balance

    auto_buy_manager.app_approved_buys_today = lambda symbol: (
        auto_buy_manager.CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY
    )
    auto_buy_manager.app_buy_cooldown_active = lambda symbol: (False, "no app cooldown")
    auto_buy_manager.recent_sell_active = lambda symbol: (False, "no recent app sell")
    auto_buy_manager.broker_positions_and_balance = lambda: ([], 10_000.0)

    try:
        auto_buy_manager.is_cash_mode = lambda: False
        ok, reason, details = auto_buy_manager.risk_cross_check("AMZN")
        assert_equal(ok, True, "paper risk check")
        assert_equal(reason, "risk cross-check passed", "paper risk reason")

        auto_buy_manager.is_cash_mode = lambda: True
        ok, reason, details = auto_buy_manager.risk_cross_check("AMZN")
        assert_equal(ok, False, "cash risk check")
        if "app daily symbol buy limit reached" not in reason:
            raise AssertionError(f"expected daily symbol cap, got {reason!r}")
    finally:
        auto_buy_manager.is_cash_mode = old_is_cash_mode
        auto_buy_manager.app_approved_buys_today = old_buys_today
        auto_buy_manager.app_buy_cooldown_active = old_buy_cooldown
        auto_buy_manager.recent_sell_active = old_recent_sell
        auto_buy_manager.broker_positions_and_balance = old_positions


def test_auto_buy_capacity_blocks_when_active_position_cap_is_full():
    old_active_cap = auto_buy_manager.AUTO_BUY_MAX_ACTIVE_POSITIONS
    old_daily_cap = auto_buy_manager.AUTO_BUY_MAX_DAILY_ORDERS
    old_held_symbols = auto_buy_manager.held_symbols
    old_orders_today = auto_buy_manager.auto_buy_orders_today
    auto_buy_manager.AUTO_BUY_MAX_ACTIVE_POSITIONS = 2
    auto_buy_manager.AUTO_BUY_MAX_DAILY_ORDERS = 12
    auto_buy_manager.held_symbols = lambda: {"AAPL", "MSFT"}
    auto_buy_manager.auto_buy_orders_today = lambda: 0
    try:
        ok, reason = auto_buy_capacity_check()
    finally:
        auto_buy_manager.AUTO_BUY_MAX_ACTIVE_POSITIONS = old_active_cap
        auto_buy_manager.AUTO_BUY_MAX_DAILY_ORDERS = old_daily_cap
        auto_buy_manager.held_symbols = old_held_symbols
        auto_buy_manager.auto_buy_orders_today = old_orders_today

    assert_equal(ok, False, "capacity ok")
    if "active auto-buy position cap reached" not in reason:
        raise AssertionError(f"unexpected capacity reason: {reason}")


def test_auto_buy_capacity_allows_replacement_when_flat_under_gross_cap():
    old_active_cap = auto_buy_manager.AUTO_BUY_MAX_ACTIVE_POSITIONS
    old_daily_cap = auto_buy_manager.AUTO_BUY_MAX_DAILY_ORDERS
    old_held_symbols = auto_buy_manager.held_symbols
    old_orders_today = auto_buy_manager.auto_buy_orders_today
    auto_buy_manager.AUTO_BUY_MAX_ACTIVE_POSITIONS = 3
    auto_buy_manager.AUTO_BUY_MAX_DAILY_ORDERS = 12
    auto_buy_manager.held_symbols = lambda: set()
    auto_buy_manager.auto_buy_orders_today = lambda: 3
    try:
        ok, reason = auto_buy_capacity_check()
    finally:
        auto_buy_manager.AUTO_BUY_MAX_ACTIVE_POSITIONS = old_active_cap
        auto_buy_manager.AUTO_BUY_MAX_DAILY_ORDERS = old_daily_cap
        auto_buy_manager.held_symbols = old_held_symbols
        auto_buy_manager.auto_buy_orders_today = old_orders_today

    assert_equal(ok, True, "capacity ok")
    if "daily_orders=3/12" not in reason:
        raise AssertionError(f"unexpected capacity reason: {reason}")


def test_auto_buy_capacity_blocks_at_gross_daily_circuit_cap():
    old_active_cap = auto_buy_manager.AUTO_BUY_MAX_ACTIVE_POSITIONS
    old_daily_cap = auto_buy_manager.AUTO_BUY_MAX_DAILY_ORDERS
    old_held_symbols = auto_buy_manager.held_symbols
    old_orders_today = auto_buy_manager.auto_buy_orders_today
    auto_buy_manager.AUTO_BUY_MAX_ACTIVE_POSITIONS = 3
    auto_buy_manager.AUTO_BUY_MAX_DAILY_ORDERS = 3
    auto_buy_manager.held_symbols = lambda: set()
    auto_buy_manager.auto_buy_orders_today = lambda: 3
    try:
        ok, reason = auto_buy_capacity_check()
    finally:
        auto_buy_manager.AUTO_BUY_MAX_ACTIVE_POSITIONS = old_active_cap
        auto_buy_manager.AUTO_BUY_MAX_DAILY_ORDERS = old_daily_cap
        auto_buy_manager.held_symbols = old_held_symbols
        auto_buy_manager.auto_buy_orders_today = old_orders_today

    assert_equal(ok, False, "capacity ok")
    if "daily auto-buy gross order cap reached" not in reason:
        raise AssertionError(f"unexpected capacity reason: {reason}")


def test_log_auto_buy_order_writes_canonical_trade_row():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT,
                    action TEXT,
                    signal_price REAL,
                    approved INTEGER,
                    rejection_reason TEXT,
                    confidence TEXT,
                    position_size_pct REAL,
                    stop_loss_pct REAL,
                    take_profit_pct REAL,
                    order_id TEXT,
                    order_status TEXT,
                    qty INTEGER,
                    fill_price REAL,
                    market_bias TEXT,
                    risk_level TEXT,
                    entry_quality TEXT,
                    session_trend_label TEXT,
                    session_trend_score REAL,
                    session_return_pct REAL,
                    session_momentum_5m_pct REAL,
                    session_momentum_15m_pct REAL,
                    session_momentum_30m_pct REAL,
                    session_distance_from_vwap_pct REAL,
                    setup_label TEXT,
                    setup_policy_action TEXT,
                    setup_policy_reason TEXT,
                    prediction_score REAL,
                    prediction_decision TEXT,
                    prediction_reason TEXT,
                    ml_prediction_score REAL,
                    ml_prediction_bucket TEXT,
                    buy_opportunity_score REAL,
                    buy_opportunity_recommendation TEXT,
                    buy_opportunity_reason TEXT,
                    session_momentum_severity TEXT,
                    effective_size_cap_pct REAL,
                    dominant_limiter TEXT
                )
                """
            )

        old_path = auto_buy_manager.DB_PATH
        auto_buy_manager.DB_PATH = db_path
        try:
            wrote = log_auto_buy_order(
                {
                    "symbol": "SOFI",
                    "decision": "strong_buy_candidate",
                    "score": 18,
                    "reason": "test reason",
                    "market_bias": "buy",
                    "risk_level": "medium",
                    "entry_quality": "good_if_holds_gap",
                    "session_trend_label": "strong_uptrend",
                    "session_trend_score": 8,
                    "session_return_pct": 1.2,
                    "momentum_5m_pct": 0.2,
                    "momentum_15m_pct": 0.4,
                    "momentum_30m_pct": 0.7,
                    "distance_from_vwap_pct": 0.5,
                    "setup_label": "above_vwap_strength_continuation",
                    "setup_recommendation": "favorable",
                },
                {
                    "order_id": "auto-order-1",
                    "status": "pending_new",
                    "qty": 10,
                    "current_price": 16.5,
                },
            )
            wrote_again = log_auto_buy_order(
                {"symbol": "SOFI"},
                {"order_id": "auto-order-1"},
            )
        finally:
            auto_buy_manager.DB_PATH = old_path

        with sqlite3.connect(db_path) as con:
            row = con.execute(
                """
                SELECT symbol, action, approved, order_id, order_status,
                       qty, buy_opportunity_score, buy_opportunity_recommendation,
                       ml_prediction_bucket, effective_size_cap_pct, dominant_limiter
                FROM trades
                """
            ).fetchone()

        assert_equal(wrote, True, "first write")
        assert_equal(wrote_again, False, "duplicate write")
        assert_equal(row[0], "SOFI", "symbol")
        assert_equal(row[1], "buy", "action")
        assert_equal(row[2], 1, "approved")
        assert_equal(row[3], "auto-order-1", "order id")
        assert_equal(row[4], "pending_new", "order status")
        assert_equal(row[5], 10, "qty")
        assert_equal(row[6], 18.0, "score")
        assert_equal(row[7], "strong_buy_candidate", "recommendation")
        assert_equal(row[8], "unknown", "missing prediction bucket")
        assert_equal(row[9], auto_buy_manager.AUTO_BUY_POSITION_SIZE_PCT, "auto-buy size cap")
        assert_equal(row[10], "auto_buy_fixed_size", "auto-buy limiter")


def test_auto_buy_candidate_attaches_canonical_decision_trace():
    candidate = {
        "symbol": "SOFI",
        "decision": "strong_buy_candidate",
        "score": 18,
        "reason": "test reason",
        "setup_score": 88,
        "setup_label": "near_vwap",
        "prediction_score": 72,
        "session_momentum_severity": "pass",
        "session_trend_label": "strong_uptrend",
        "session_trend_score": 8,
        "effective_size_cap_pct": 0.5,
        "dominant_limiter": "auto_buy_fixed_size",
    }
    enriched = attach_canonical_decision_metadata(candidate)
    assert_equal(enriched["canonical_signal_candidate"]["source"], "auto_buy", "source")
    assert_equal(
        enriched["canonical_decision_trace"]["trace_version"],
        "decision_trace_v1",
        "trace version",
    )
    gate_ids = [row["gate_id"] for row in enriched["canonical_decision_trace"]["gate_results"]]
    if "intelligence_adjudicator" not in gate_ids:
        raise AssertionError("missing intelligence gate in auto-buy trace")
    if "final_sizing" not in gate_ids:
        raise AssertionError("missing sizing gate in auto-buy trace")


def test_log_candidate_mirrors_to_candidate_universe():
    class Quote:
        bid_price = 10.0
        ask_price = 10.1
        bid_size = 100
        ask_size = 200
        timestamp = "2026-06-02T10:00:00-04:00"

    class CandidateReferenceService:
        def candidate_reference_snapshot(self, symbol):
            quote = Quote()
            mid = (quote.bid_price + quote.ask_price) / 2.0
            spread_pct = (quote.ask_price - quote.bid_price) / mid * 100.0
            return {
                "reference_capture_status": "captured",
                "reference_price": round(mid, 6),
                "reference_price_source": "quote_mid",
                "bid": quote.bid_price,
                "ask": quote.ask_price,
                "mid": round(mid, 6),
                "spread_pct": round(spread_pct, 6),
                "bid_size": quote.bid_size,
                "ask_size": quote.ask_size,
                "quote_ts": quote.timestamp,
            }

        def get_latest_quote(self, symbol):
            return Quote()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        old_path = auto_buy_manager.DB_PATH
        old_reference_service = auto_buy_manager.candidate_reference_service
        auto_buy_manager.DB_PATH = db_path
        auto_buy_manager.candidate_reference_service = CandidateReferenceService()
        try:
            auto_buy_manager.log_candidate(
                {
                    "symbol": "SOFI",
                    "decision": "watch",
                    "score": auto_buy_manager.AUTO_BUY_MIN_SCORE - 0.5,
                    "reason": "near threshold test",
                    "market_bias": "buy",
                    "session_trend_label": "strong_uptrend",
                    "setup_label": "breakout",
                    "symbol_pattern": "trend_continuation_with_participation",
                    "pattern_runtime_effect": "observe_only_no_live_authority",
                    "five_day_return_pct": 3.2,
                    "rolling_continuation_score": 4,
                    "rolling_momentum_last_5_market_days": [
                        "2026-05-28",
                        "2026-05-29",
                        "2026-06-01",
                        "2026-06-02",
                        "2026-06-03",
                    ],
                    "rolling_momentum_source": "rolling_momentum_json",
                },
                live_buy_enabled=False,
            )
        finally:
            auto_buy_manager.DB_PATH = old_path
            auto_buy_manager.candidate_reference_service = old_reference_service

        with sqlite3.connect(db_path) as con:
            row = con.execute(
                """
                SELECT symbol, action, candidate_kind, candidate_status,
                       decision, source, runtime_effect, candidate_json
                FROM candidate_universe
                """
            ).fetchone()

        assert_equal(row[0], "SOFI", "symbol")
        assert_equal(row[1], "buy", "action")
        assert_equal(row[2], "entry", "kind")
        assert_equal(row[3], "near_threshold", "status")
        assert_equal(row[4], "watch", "decision")
        assert_equal(row[5], "auto_buy_manager", "source")
        assert_equal(row[6], "candidate_capture_only_no_live_authority", "effect")
        if "trend_continuation_with_participation" not in row[7]:
            raise AssertionError("candidate universe payload did not include symbol pattern")
        payload = json.loads(row[7])
        candidate_payload = payload["candidate"]
        assert_equal(candidate_payload["reference_price"], 10.05, "reference price")
        assert_equal(candidate_payload["reference_price_source"], "quote_mid", "reference source")
        assert_equal(candidate_payload["spread_pct"], 0.995025, "spread pct")
        assert_equal(candidate_payload["five_day_return_pct"], 3.2, "five-day return")
        assert_equal(candidate_payload["rolling_continuation_score"], 4, "rolling score")
        assert_equal(
            candidate_payload["rolling_momentum_source"],
            "rolling_momentum_json",
            "rolling source",
        )


def test_bucking_fading_tape_does_not_hard_block():
    old_prediction_context = auto_buy_manager.auto_buy_prediction_context
    auto_buy_manager.auto_buy_prediction_context = lambda symbol: {
        "available": False,
        "ml_prediction_bucket": "unknown",
        "ml_prediction_score": None,
        "ml_prediction_sample_size": None,
    }
    try:
        candidate = evaluate_auto_buy_candidate(
            symbol="MDB",
            session={
                "trend_label": "fading",
                "trend_score": -3,
                "session_return_pct": 7.17,
                "momentum_5m_pct": 0.10,
                "momentum_15m_pct": -0.30,
                "momentum_30m_pct": -0.50,
                "distance_from_vwap_pct": 0.50,
            },
            feature={
                "setup_recommendation": "watch",
                "setup_label": "bucking_tape_test",
                "setup_score": 55,
                "relative_strength_5m": 0.45,
                "ret_5m": 0.20,
                "ret_15m": -0.10,
                "distance_from_vwap": 0.50,
                "momentum_acceleration_pct": 0.04,
            },
            context={"bias": "buy", "entry_quality": "good_on_pullbacks", "risk_level": "low"},
            held=set(),
            signal_source="internal_bar_only",
        )
    finally:
        auto_buy_manager.auto_buy_prediction_context = old_prediction_context

    assert candidate["hard_block_reason"] is None
    assert "bucking_fading_tape" in candidate["reason"]
    assert "15m_falling_soft" in candidate["reason"]
    assert "30m_falling_soft" in candidate["reason"]


def test_learned_tiebreaker_can_promote_watch_candidate_in_paper_mode():
    old_tiebreaker = auto_buy_manager.learned_auto_buy_tiebreaker_decision
    old_cash_mode = auto_buy_manager.is_cash_mode
    old_enabled = auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_ENABLED
    old_gap = auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP
    auto_buy_manager.learned_auto_buy_tiebreaker_decision = lambda candidate: {
        "qualified": True,
        "reason": "symbol_pattern_bucket_passed",
        "evidence": {
            "qualified_bucket": "symbol_pattern",
            "symbol_pattern_stats": {
                "sample_size": 42,
                "win_rate": 0.64,
                "avg_return_pct": 0.55,
                "avg_mfe_pct": 1.8,
            },
        },
    }
    auto_buy_manager.is_cash_mode = lambda: False
    auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_ENABLED = True
    auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP = 10.0
    try:
        feature = favorable_feature()
        feature["setup_recommendation"] = "watch"
        feature["setup_score"] = 58
        candidate = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=strong_session(),
            feature=feature,
            context=buy_context(),
            held=set(),
            signal_source="internal_bar_only",
        )
    finally:
        auto_buy_manager.learned_auto_buy_tiebreaker_decision = old_tiebreaker
        auto_buy_manager.is_cash_mode = old_cash_mode
        auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_ENABLED = old_enabled
        auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP = old_gap

    assert_equal(candidate["decision"], "strong_buy_candidate", "decision")
    assert_equal(candidate["learned_tiebreaker_applied"], True, "tiebreaker applied")
    assert_equal(
        candidate["learned_tiebreaker_runtime_effect"],
        "paper_only_tiebreaker_authority",
        "runtime effect",
    )
    if "learned_tiebreaker_promoted" not in candidate["reason"]:
        raise AssertionError(f"missing learned tiebreaker reason: {candidate['reason']}")


def test_learned_tiebreaker_does_not_override_hard_blocks():
    old_tiebreaker = auto_buy_manager.learned_auto_buy_tiebreaker_decision
    old_cash_mode = auto_buy_manager.is_cash_mode
    old_enabled = auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_ENABLED
    auto_buy_manager.learned_auto_buy_tiebreaker_decision = lambda candidate: {
        "qualified": True,
        "reason": "symbol_pattern_bucket_passed",
        "evidence": {},
    }
    auto_buy_manager.is_cash_mode = lambda: False
    auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_ENABLED = True
    try:
        session = strong_session()
        session["session_return_pct"] = 3.2
        session["distance_from_vwap_pct"] = 1.5
        feature = favorable_feature()
        feature["setup_label"] = "above_vwap_strength_continuation"
        candidate = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=session,
            feature=feature,
            context=buy_context(),
            held=set(),
            signal_source="internal_bar_only",
        )
    finally:
        auto_buy_manager.learned_auto_buy_tiebreaker_decision = old_tiebreaker
        auto_buy_manager.is_cash_mode = old_cash_mode
        auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_ENABLED = old_enabled

    assert_equal(candidate["decision"], "skip", "decision")
    assert_equal(candidate["severity"], "blocked", "severity")
    assert_equal(candidate["learned_tiebreaker_allowed"], False, "tiebreaker allowed")
    assert_equal(candidate["learned_tiebreaker_applied"], False, "tiebreaker applied")


def test_learned_tiebreaker_can_override_soft_intelligence_blocks_in_paper_mode():
    old_tiebreaker = auto_buy_manager.learned_auto_buy_tiebreaker_decision
    old_cash_mode = auto_buy_manager.is_cash_mode
    old_enabled = auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_ENABLED
    old_gap = auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP
    auto_buy_manager.learned_auto_buy_tiebreaker_decision = lambda candidate: {
        "qualified": True,
        "reason": "pattern_bucket_passed",
        "evidence": {"qualified_bucket": "pattern"},
    }
    auto_buy_manager.is_cash_mode = lambda: False
    auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_ENABLED = True
    auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP = 20.0
    try:
        session = strong_session()
        session["trend_label"] = "downtrend"
        session["trend_score"] = -3
        session["momentum_15m_pct"] = 0.25
        session["momentum_30m_pct"] = 0.45
        feature = favorable_feature()
        feature["setup_score"] = 72
        candidate = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=session,
            feature=feature,
            context=buy_context(),
            held=set(),
            signal_source="internal_bar_only",
        )
    finally:
        auto_buy_manager.learned_auto_buy_tiebreaker_decision = old_tiebreaker
        auto_buy_manager.is_cash_mode = old_cash_mode
        auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_ENABLED = old_enabled
        auto_buy_manager.AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP = old_gap

    assert_equal(candidate["decision"], "strong_buy_candidate", "decision")
    assert_equal(candidate["learned_tiebreaker_applied"], True, "tiebreaker applied")
    assert_equal(candidate["learned_tiebreaker_soft_blocks_only"], True, "soft blocks only")
    assert_equal(candidate["learned_tiebreaker_overrode_soft_blocks"], True, "soft block override")
    assert_equal(candidate["hard_block_reason"], None, "hard block reason")
    if "negative_session" not in candidate["learned_tiebreaker_original_hard_block_reason"]:
        raise AssertionError("missing original soft block reason")


def test_layered_ml_can_promote_near_threshold_auto_buy_candidate_in_paper_mode():
    old_context = auto_buy_manager.auto_buy_layered_ml_context
    old_cash_mode = auto_buy_manager.is_cash_mode
    old_enabled = auto_buy_manager.AUTO_BUY_LAYERED_ML_ENABLED
    old_promotion = auto_buy_manager.AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED
    auto_buy_manager.is_cash_mode = lambda: False
    auto_buy_manager.AUTO_BUY_LAYERED_ML_ENABLED = True
    auto_buy_manager.AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED = True
    auto_buy_manager.auto_buy_layered_ml_context = lambda **kwargs: {
        "enabled": True,
        "available": True,
        "runtime_effect": "paper_bounded_auto_buy_intelligence_authority",
        "final_instruction": "paper_approval",
        "final_size_pct": 0.5,
        "ensemble_probability_pct": 72.0,
        "meta_label_effect": "paper_approval",
        "meta_label_instruction": "pass",
        "master_confidence_score": 72.0,
        "paper_recommendation": "paper_trade_candidate",
        "reason": "test layered approval",
        "decision": {"final_instruction": "paper_approval"},
        "historical_bar_paper_strategy": {"master_confidence_score": 72.0},
        "bar_pattern_features": {"symbol": "AMZN"},
    }
    try:
        candidate = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session={
                "trend_label": "developing_uptrend",
                "trend_score": 3,
                "session_return_pct": 0.2,
                "momentum_5m_pct": 0.0,
                "momentum_15m_pct": 0.25,
                "momentum_30m_pct": 0.0,
                "distance_from_vwap_pct": 0.4,
            },
            feature={
                **favorable_feature(),
                "setup_recommendation": "watch",
                "setup_score": 55,
            },
            context={"bias": "neutral", "entry_quality": "neutral", "risk_level": "medium"},
            held=set(),
        )
    finally:
        auto_buy_manager.auto_buy_layered_ml_context = old_context
        auto_buy_manager.is_cash_mode = old_cash_mode
        auto_buy_manager.AUTO_BUY_LAYERED_ML_ENABLED = old_enabled
        auto_buy_manager.AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED = old_promotion

    assert_equal(candidate["decision"], "strong_buy_candidate", "decision")
    assert_equal(candidate["layered_ml_promotion_applied"], True, "layered promotion")
    assert_equal(candidate["layered_ml_final_instruction"], "paper_approval", "instruction")
    if "layered_ml_promoted" not in candidate["reason"]:
        raise AssertionError("missing layered ML promotion reason")


def test_layered_ml_veto_blocks_otherwise_strong_auto_buy_candidate_in_paper_mode():
    old_context = auto_buy_manager.auto_buy_layered_ml_context
    old_cash_mode = auto_buy_manager.is_cash_mode
    old_enabled = auto_buy_manager.AUTO_BUY_LAYERED_ML_ENABLED
    old_veto = auto_buy_manager.AUTO_BUY_LAYERED_ML_VETO_HARD_BLOCK_ENABLED
    auto_buy_manager.is_cash_mode = lambda: False
    auto_buy_manager.AUTO_BUY_LAYERED_ML_ENABLED = True
    auto_buy_manager.AUTO_BUY_LAYERED_ML_VETO_HARD_BLOCK_ENABLED = True
    auto_buy_manager.auto_buy_layered_ml_context = lambda **kwargs: {
        "enabled": True,
        "available": True,
        "runtime_effect": "paper_bounded_auto_buy_intelligence_authority",
        "final_instruction": "veto",
        "final_size_pct": 0.0,
        "ensemble_probability_pct": 42.0,
        "meta_label_effect": "ensemble_probability_veto",
        "meta_label_instruction": "veto",
        "master_confidence_score": 42.0,
        "paper_recommendation": "paper_avoid",
        "reason": "test layered veto",
        "decision": {"final_instruction": "veto"},
        "historical_bar_paper_strategy": {"master_confidence_score": 42.0},
        "bar_pattern_features": {"symbol": "AMZN"},
    }
    try:
        candidate = evaluate_auto_buy_candidate(
            symbol="AMZN",
            session=strong_session(),
            feature=favorable_feature(),
            context=buy_context(),
            held=set(),
        )
    finally:
        auto_buy_manager.auto_buy_layered_ml_context = old_context
        auto_buy_manager.is_cash_mode = old_cash_mode
        auto_buy_manager.AUTO_BUY_LAYERED_ML_ENABLED = old_enabled
        auto_buy_manager.AUTO_BUY_LAYERED_ML_VETO_HARD_BLOCK_ENABLED = old_veto

    assert_equal(candidate["decision"], "skip", "decision")
    assert_equal(candidate["severity"], "blocked", "severity")
    if "layered_ml_veto" not in str(candidate["hard_block_reason"]):
        raise AssertionError("missing layered ML hard block reason")


def main():
    tests = [
        test_strong_internal_candidate_scores_as_buy_candidate,
        test_five_day_rolling_context_is_scored_and_returned,
        test_held_symbol_is_skipped,
        test_negative_session_blocks_candidate,
        test_weak_ml_prediction_blocks_auto_buy_candidate,
        test_weak_ml_bucket_blocks_even_with_thin_sample,
        test_intraday_feedback_blocks_repeated_losing_pattern,
        test_paper_strong_evidence_promotes_setup_soft_block_only,
        test_paper_strong_evidence_does_not_promote_weak_ml_block,
        test_watch_setup_cannot_become_strong_buy_by_default,
        test_early_constructive_build_gets_buy_candidate_boost,
        test_mature_chase_extension_is_penalized_and_extreme_chase_blocks,
        test_unclassified_extended_vwap_blocks_candidate,
        test_strategy_memory_caution_reduces_auto_buy_score,
        test_strategy_memory_avoid_blocks_auto_buy_candidate,
        test_tradingview_symbols_need_higher_auto_buy_threshold,
        test_internal_all_mode_removes_tradingview_threshold_penalty,
        test_early_session_buffer_skips_collection,
        test_live_buy_requires_market_open_and_env_flag,
        test_live_auto_buy_does_not_execute_tradingview_alert_symbols_by_default,
        test_internal_all_mode_stays_candidate_only_for_tradingview_symbols,
        test_cash_safe_daily_symbol_cap_only_applies_in_cash_modes,
        test_auto_buy_capacity_blocks_when_active_position_cap_is_full,
        test_auto_buy_capacity_allows_replacement_when_flat_under_gross_cap,
        test_auto_buy_capacity_blocks_at_gross_daily_circuit_cap,
        test_bucking_fading_tape_does_not_hard_block,
        test_learned_tiebreaker_can_promote_watch_candidate_in_paper_mode,
        test_learned_tiebreaker_does_not_override_hard_blocks,
        test_learned_tiebreaker_can_override_soft_intelligence_blocks_in_paper_mode,
        test_layered_ml_can_promote_near_threshold_auto_buy_candidate_in_paper_mode,
        test_layered_ml_veto_blocks_otherwise_strong_auto_buy_candidate_in_paper_mode,
        test_log_auto_buy_order_writes_canonical_trade_row,
        test_auto_buy_candidate_attaches_canonical_decision_trace,
        test_log_candidate_mirrors_to_candidate_universe,
    ]

    for test in tests:
        old_prediction_context = auto_buy_manager.auto_buy_prediction_context
        old_memory = auto_buy_manager.memory_for_signal
        old_runtime = {key: getattr(auto_buy_manager, key) for key in AUTO_BUY_RUNTIME_DEFAULTS}
        auto_buy_manager.auto_buy_prediction_context = lambda symbol: {
            "available": False,
            "ml_prediction_bucket": "unknown",
            "ml_prediction_score": None,
            "ml_prediction_sample_size": None,
        }
        auto_buy_manager.memory_for_signal = lambda symbol, context: {
            "available": False,
            "recommendation": "none",
            "min_setup_score": None,
            "reason": "test default strategy memory unavailable",
        }
        try:
            reset_auto_buy_runtime_defaults()
            test()
            print(f"[OK] {test.__name__}")
        finally:
            auto_buy_manager.auto_buy_prediction_context = old_prediction_context
            auto_buy_manager.memory_for_signal = old_memory
            for key, value in old_runtime.items():
                setattr(auto_buy_manager, key, value)

    print()
    print(f"All {len(tests)} auto-buy manager tests passed.")


if __name__ == "__main__":
    main()
