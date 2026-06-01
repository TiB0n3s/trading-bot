"""
Focused tests for internal auto-buy candidate scoring.

Run:
  python3 tests/test_auto_buy_manager.py
"""

import sys
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auto_buy_manager import evaluate_auto_buy_candidate
from auto_buy_manager import log_auto_buy_order
from auto_buy_manager import maybe_execute_auto_buy
from auto_buy_manager import should_collect_candidates
import auto_buy_manager


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


def test_tradingview_symbols_need_higher_auto_buy_threshold():
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
    assert_equal(webhook_symbol["strong_buy_threshold"], auto_buy_manager.AUTO_BUY_MIN_SCORE + 4.0, "threshold")


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
    assert_equal(candidate["live_block_reason"], "live not requested or AUTO_BUY_LIVE_BUYS is false", "block reason")


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
        "tradingview alert symbol requires webhook approval path",
        "block reason",
    )


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
                    buy_opportunity_score REAL,
                    buy_opportunity_recommendation TEXT,
                    buy_opportunity_reason TEXT
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
                       qty, buy_opportunity_score, buy_opportunity_recommendation
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


def test_log_candidate_mirrors_to_candidate_universe():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        old_path = auto_buy_manager.DB_PATH
        auto_buy_manager.DB_PATH = db_path
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
                },
                live_buy_enabled=False,
            )
        finally:
            auto_buy_manager.DB_PATH = old_path

        with sqlite3.connect(db_path) as con:
            row = con.execute(
                """
                SELECT symbol, action, candidate_kind, candidate_status,
                       decision, source, runtime_effect
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



def test_bucking_fading_tape_does_not_hard_block():
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

    assert candidate["hard_block_reason"] is None
    assert "bucking_fading_tape" in candidate["reason"]
    assert "15m_falling_soft" in candidate["reason"]
    assert "30m_falling_soft" in candidate["reason"]


def main():
    tests = [
        test_strong_internal_candidate_scores_as_buy_candidate,
        test_held_symbol_is_skipped,
        test_negative_session_blocks_candidate,
        test_tradingview_symbols_need_higher_auto_buy_threshold,
        test_early_session_buffer_skips_collection,
        test_live_buy_requires_market_open_and_env_flag,
        test_live_auto_buy_does_not_execute_tradingview_alert_symbols_by_default,
        test_bucking_fading_tape_does_not_hard_block,
        test_log_auto_buy_order_writes_canonical_trade_row,
        test_log_candidate_mirrors_to_candidate_universe,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} auto-buy manager tests passed.")


if __name__ == "__main__":
    main()
