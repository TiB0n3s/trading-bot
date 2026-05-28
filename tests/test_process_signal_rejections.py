#!/usr/bin/env python3
"""
Tests for app.py process_signal rejection paths and /webhook HTTP validation.

process_signal rejection categories covered:
  ghost_sell, market_hours, circuit_breaker, duplicate_webhook,
  symbol_override, cooldown, churn_window, churn_price,
  daily_symbol_buy_limit, session_trade_count, exposure_cap,
  macro_risk, macro_position_limit, trend_confirmation (buy + sell),
  fundamental_score, chase_prevention, sell_profit_threshold,
  sell_discipline

/webhook HTTP layer covered:
  missing/wrong secret → 401
  non-JSON body → 400
  missing action or symbol → 400
  unapproved symbol → 400
  invalid action → 400
  price out of sanity range → 400
  non-positive price → 400
  valid signal accepted → 200
"""

from __future__ import annotations

import os
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Required before importing app / broker / alpaca_trade_api
os.environ.setdefault("ALPACA_API_KEY", "test-key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test-secret")
os.environ.setdefault("APCA_API_KEY_ID", "test-key")
os.environ.setdefault("APCA_API_SECRET_KEY", "test-secret")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("EXECUTION_MODE", "paper")

import app as _app
from symbols_config import APPROVED_SYMBOLS, PRICE_RANGES

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy, got {value!r}")


def assert_in(value, container, label):
    if value not in container:
        raise AssertionError(f"{label}: {value!r} not in {container!r}")


# ---------------------------------------------------------------------------
# Signal builders
# ---------------------------------------------------------------------------

_SYMBOL = "AAPL"
_LOW, _HIGH = PRICE_RANGES[_SYMBOL]
_PRICE = (_LOW + _HIGH) / 2  # guaranteed within sanity range

_SECRET = os.environ["WEBHOOK_SECRET"]
_ET_NOW = datetime(2024, 6, 10, 11, 30, 0, tzinfo=timezone.utc)


def _buy(symbol=_SYMBOL, price=_PRICE, **extra):
    return {"action": "buy", "symbol": symbol, "price": price, **extra}


def _sell(symbol=_SYMBOL, price=_PRICE, **extra):
    return {"action": "sell", "symbol": symbol, "price": price, **extra}


def _account(**overrides):
    base = {
        "balance": 100_000.0,
        "portfolio_value": 100_000.0,
        "open_position_count": 2,
        "daily_pnl_pct": 0.5,
        "buying_power": 80_000.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Patch environment
# ---------------------------------------------------------------------------

def _base_patches(**overrides):
    """
    Return a fresh dict of (target → mock) pairs that suppress all external
    I/O and let tests control exactly which gate fires.

    Defaults keep every gate open (pass-through). Individual tests override
    the specific condition they want to trigger.
    """
    patches = {
        # Market state loading — filesystem I/O, no-op in tests
        "app._load_market_context": MagicMock(),
        # Fail-open advisory context
        "app.rolling_symbol_context": MagicMock(return_value=None),
        "app.prior_session_context": MagicMock(return_value=None),
        "app.build_tape_context": MagicMock(
            return_value={"ok": True, "bar_count": 5, "classification": {}, "state": {}}
        ),
        "app.get_momentum": MagicMock(return_value=None),
        # Setup/signal history
        "app._build_setup_observation": MagicMock(return_value={}),
        "app._remember_favorable_setup": MagicMock(),
        "app._get_recent_favorable_setup": MagicMock(return_value=None),
        "app._refresh_signal_history": MagicMock(),
        "app._compute_trend": MagicMock(
            return_value={
                "direction": "bullish",
                "strength": "confirmed",
                "consecutive_count": 5,
                "last_signal": "buy",
                "flip_event": False,
                "confirmed_entry": True,
                "confirmed_exit": False,
                "bullish_candidate": False,
                "bearish_candidate": False,
                "previous_opposite_count": 0,
            }
        ),
        # Dedup / overrides — open by default
        "app._is_duplicate_webhook": MagicMock(return_value=False),
        "app._symbol_override_block": MagicMock(return_value=None),
        # Time — fixed mid-session so market_hours passes
        "app.now_et": MagicMock(return_value=_ET_NOW),
        "app.is_market_hours": MagicMock(return_value=True),
        # Position tracking
        "app.get_position": MagicMock(return_value=None),
        "app._has_open_position_db": MagicMock(return_value=True),
        # Rate limits / churn — open by default
        "app._read_cooldown": MagicMock(return_value=None),
        "app._read_recent_sell": MagicMock(return_value=None),
        "app._successful_buys_today": MagicMock(return_value=0),
        "app._filled_buys_today": MagicMock(return_value=0),
        "app._count_second_look_blocks_today": MagicMock(return_value=0),
        # Exposure / cluster
        "app._cluster_exposure": MagicMock(return_value=[]),
        # Macro — safe defaults
        "app.get_macro_risk": MagicMock(
            return_value={"block_new_buys": False, "max_new_positions": 8, "reason": ""}
        ),
        # Scoring helpers
        "app.evaluate_buy_opportunity": MagicMock(
            return_value={
                "buy_opportunity_score": 50,
                "buy_opportunity_recommendation": "neutral",
                "buy_opportunity_reason": "",
            }
        ),
        # Session momentum — unavailable by default (fail-open)
        "app.get_latest_session_momentum": MagicMock(return_value=None),
        "app._session_momentum_is_fresh": MagicMock(return_value=False),
        "app._evaluate_session_momentum_gate": MagicMock(return_value=False),
        # Trend confirmation helpers
        "app._required_buy_confirmations": MagicMock(
            return_value={"required_buy_confirmations": 3, "reason": "default"}
        ),
        "app.is_fast_lane_buy_flip": MagicMock(return_value=True),  # default: fast-lane bypasses gate
        "app._required_sell_confirmations": MagicMock(
            return_value={"required_sell_confirmations": 2, "reason": "default"}
        ),
        "app.is_fast_lane_sell_flip": MagicMock(return_value=True),  # default: fast-lane bypasses gate
        # Prediction / signal quality (observe-only, no blocking by default)
        "app.evaluate_signal_quality_gate": MagicMock(return_value={"decision": "pass"}),
        "app.evaluate_prediction_gate": MagicMock(
            return_value={"prediction_decision": "observe_only", "decision": "pass"}
        ),
        # Downstream gates (tested separately; default to pass)
        "app._live_bias_override": MagicMock(return_value={}),
        "app._one_bar_confirmation_hold": MagicMock(return_value=(False, "")),
        "app._pre_order_safety_check": MagicMock(return_value=True),
        "app._sell_continuation_delay_reason": MagicMock(return_value=None),
        # Decision engine — always reject so tests never hit the broker
        "app.evaluate_signal": MagicMock(
            return_value={
                "approved": False,
                "reason": "test_sentinel_claude_block",
                "position_size_pct": 1.5,
                "stop_loss_pct": 0.5,
                "take_profit_pct": 1.5,
                "confidence": "medium",
            }
        ),
        # DB writes — capture without touching trades.db
        "app.log_rejection": MagicMock(),
        "app.log_trade": MagicMock(),
        "app._mark_webhook_event_status": MagicMock(),
        # Stale-signal check — fresh by default
        "app._is_signal_stale": MagicMock(return_value=(False, 0.0, "fresh")),
        # Portfolio rotation — disabled by default
        "app._try_portfolio_rotation": MagicMock(return_value=(False, "observe_only", {})),
        "app._get_weakest_position_context": MagicMock(return_value=None),
    }
    patches.update(overrides)
    return patches


class _Env:
    """Apply a set of patches to the app module for one test."""

    def __init__(self, **overrides):
        self._patch_map = _base_patches(**overrides)
        self._stack = ExitStack()

    def __enter__(self):
        for target, mock in self._patch_map.items():
            try:
                self._stack.enter_context(patch(target, new=mock))
            except AttributeError:
                pass  # attribute added after import — skip
        return self

    def __exit__(self, *args):
        self._stack.close()

    # Convenience accessors for captured log_rejection calls
    def rejected(self):
        mock = self._patch_map.get("app.log_rejection")
        return mock is not None and mock.called

    def rejection_category(self):
        mock = self._patch_map.get("app.log_rejection")
        if mock and mock.called:
            args = mock.call_args[0]
            return args[2] if len(args) > 2 else None
        return None

    def rejection_reason(self):
        mock = self._patch_map.get("app.log_rejection")
        if mock and mock.called:
            args = mock.call_args[0]
            return args[3] if len(args) > 3 else None
        return None


# ---------------------------------------------------------------------------
# /webhook HTTP route tests
# ---------------------------------------------------------------------------

def test_webhook_rejects_missing_secret():
    _app.app.testing = True
    client = _app.app.test_client()
    resp = client.post("/webhook", json=_buy())
    assert_equal(resp.status_code, 401, "missing secret → 401")


def test_webhook_rejects_wrong_secret():
    _app.app.testing = True
    client = _app.app.test_client()
    resp = client.post(
        "/webhook",
        json=_buy(),
        headers={"X-Webhook-Secret": "wrong-secret"},
    )
    assert_equal(resp.status_code, 401, "wrong secret → 401")


def test_webhook_rejects_non_json():
    _app.app.testing = True
    client = _app.app.test_client()
    resp = client.post(
        "/webhook",
        data="not json at all",
        content_type="text/plain",
        headers={"X-Webhook-Secret": _SECRET},
    )
    assert_equal(resp.status_code, 400, "non-JSON → 400")


def test_webhook_rejects_invalid_action():
    _app.app.testing = True
    client = _app.app.test_client()
    resp = client.post(
        "/webhook",
        json={"action": "hold", "symbol": _SYMBOL, "price": _PRICE},
        headers={"X-Webhook-Secret": _SECRET},
    )
    assert_equal(resp.status_code, 400, "invalid action → 400")


def test_webhook_rejects_unapproved_symbol():
    _app.app.testing = True
    client = _app.app.test_client()
    resp = client.post(
        "/webhook",
        json={"action": "buy", "symbol": "DOESNOTEXIST", "price": 10.0},
        headers={"X-Webhook-Secret": _SECRET},
    )
    assert_equal(resp.status_code, 400, "unapproved symbol → 400")


def test_webhook_rejects_out_of_range_price():
    _app.app.testing = True
    client = _app.app.test_client()
    # Price far below floor
    resp = client.post(
        "/webhook",
        json={"action": "buy", "symbol": _SYMBOL, "price": 0.01},
        headers={"X-Webhook-Secret": _SECRET},
    )
    assert_equal(resp.status_code, 400, "price below sanity floor → 400")


def test_webhook_rejects_nonpositive_price():
    _app.app.testing = True
    client = _app.app.test_client()
    resp = client.post(
        "/webhook",
        json={"action": "buy", "symbol": _SYMBOL, "price": 0},
        headers={"X-Webhook-Secret": _SECRET},
    )
    assert_equal(resp.status_code, 400, "zero price → 400")


def test_webhook_accepts_valid_buy_signal():
    """A well-formed signal with correct secret queues successfully (HTTP 200)."""
    _app.app.testing = True
    submit_mock = MagicMock()
    executor_mock = MagicMock()
    executor_mock.submit = submit_mock
    with patch("app._signal_executor", executor_mock):
        with patch("app._record_webhook_event", return_value=True):
            with patch("app._mark_webhook_event_status", MagicMock()):
                client = _app.app.test_client()
                resp = client.post(
                    "/webhook",
                    json=_buy(),
                    headers={"X-Webhook-Secret": _SECRET},
                )
    assert_equal(resp.status_code, 200, "valid signal → 200")
    assert_true(submit_mock.called, "signal submitted to executor")


# ---------------------------------------------------------------------------
# process_signal rejection tests
# ---------------------------------------------------------------------------

def test_ghost_sell_blocked_when_no_db_position():
    """Sell with no tracked DB position is blocked before account state is loaded."""
    with _Env(**{"app._has_open_position_db": MagicMock(return_value=False)}) as env:
        _app.process_signal(_sell())
    assert_equal(env.rejection_category(), "ghost_sell", "category")


def test_market_hours_blocks_outside_hours():
    with _Env(**{"app.is_market_hours": MagicMock(return_value=False),
                 "app.get_mock_account_state": MagicMock(return_value=_account())}) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "market_hours", "category")


def test_circuit_breaker_blocks_buy_on_daily_loss():
    with _Env(**{
        "app.get_mock_account_state": MagicMock(
            return_value=_account(daily_pnl_pct=-4.0)
        ),
    }) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "circuit_breaker", "category")


def test_circuit_breaker_does_not_block_sell():
    """Sells must remain allowed even when the circuit breaker would fire for buys."""
    log_mock = MagicMock()
    with _Env(**{
        "app.get_mock_account_state": MagicMock(
            return_value=_account(daily_pnl_pct=-4.0)
        ),
        "app.log_rejection": log_mock,
    }):
        _app.process_signal(_sell())
    # No circuit_breaker rejection for sells
    for call in log_mock.call_args_list:
        assert call[0][2] != "circuit_breaker", "circuit_breaker must not block sells"


def test_duplicate_webhook_blocked():
    with _Env(**{
        "app._is_duplicate_webhook": MagicMock(return_value=True),
        "app.get_mock_account_state": MagicMock(return_value=_account()),
    }) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "duplicate_webhook", "category")


def test_symbol_override_blocks_signal():
    with _Env(**{
        "app._symbol_override_block": MagicMock(return_value="operator blocked this symbol"),
        "app.get_mock_account_state": MagicMock(return_value=_account()),
    }) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "symbol_override", "category")


def test_cooldown_blocks_buy_within_window():
    recent = _ET_NOW - timedelta(minutes=5)  # 5 min ago, within 15-min cooldown
    with _Env(**{
        "app._read_cooldown": MagicMock(return_value=recent),
        "app.get_mock_account_state": MagicMock(return_value=_account()),
    }) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "cooldown", "category")


def test_churn_window_blocks_buy_after_recent_sell():
    sell_time = _ET_NOW - timedelta(minutes=10)  # 10 min ago, within 30-min window
    with _Env(**{
        "app._read_recent_sell": MagicMock(return_value=(sell_time, _PRICE * 1.1)),
        "app.get_mock_account_state": MagicMock(return_value=_account()),
    }) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "churn_window", "category")


def test_churn_price_blocks_buy_near_last_sell_price():
    sell_time = _ET_NOW - timedelta(minutes=45)  # outside 30-min window
    last_sell_price = _PRICE * 1.001  # within 0.5% of current price

    def _adaptive_churn(symbol, signal_price, last_sell_price, account_state):
        return False, "test_churn_reason"

    with _Env(**{
        "app._read_recent_sell": MagicMock(return_value=(sell_time, last_sell_price)),
        "app._adaptive_churn_reentry_allowed": _adaptive_churn,
        "app.get_mock_account_state": MagicMock(return_value=_account()),
    }) as env:
        _app.process_signal(_buy(price=_PRICE))
    assert_equal(env.rejection_category(), "churn_price", "category")


def test_daily_symbol_buy_limit_blocks_at_max():
    with _Env(**{
        "app._successful_buys_today": MagicMock(return_value=999),
        "app.get_mock_account_state": MagicMock(return_value=_account()),
    }) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "daily_symbol_buy_limit", "category")


def test_session_trade_count_blocks_at_limit():
    with patch.dict(os.environ, {"SESSION_MAX_TRADE_COUNT": "1"}):
        with _Env(**{
            "app._filled_buys_today": MagicMock(return_value=1),
            "app.get_mock_account_state": MagicMock(return_value=_account()),
        }) as env:
            _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "session_trade_count", "category")


def test_exposure_cap_blocks_overexposed_buy():
    # existing position worth 5% of balance → over 4% cap
    balance = 100_000.0
    qty = 50
    current_price = 100.0  # position_value=5000 = 5% of 100k
    existing_position = {
        "qty": qty,
        "current_price": current_price,
        "avg_entry": 90.0,
    }
    with _Env(**{
        "app.get_position": MagicMock(return_value=existing_position),
        "app.get_mock_account_state": MagicMock(return_value=_account(balance=balance)),
    }) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "exposure_cap", "category")


def test_macro_risk_blocks_buy_when_regime_blocks():
    with _Env(**{
        "app.get_macro_risk": MagicMock(
            return_value={"block_new_buys": True, "max_new_positions": 0, "reason": "capital_preservation"}
        ),
        "app.get_mock_account_state": MagicMock(return_value=_account()),
    }) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "macro_risk", "category")


def test_macro_position_limit_blocks_when_full():
    with _Env(**{
        "app.get_macro_risk": MagicMock(
            return_value={"block_new_buys": False, "max_new_positions": 3, "reason": ""}
        ),
        "app.get_mock_account_state": MagicMock(
            return_value=_account(open_position_count=3)
        ),
        "app._try_portfolio_rotation": MagicMock(return_value=(False, "observe_only", {})),
    }) as env:
        _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "macro_position_limit", "category")


def test_trend_confirmation_blocks_buy_insufficient_consecutive():
    """BUY with only 1 consecutive buy is rejected when ADAPTIVE confirmation is on."""
    with _Env(**{
        "app.get_mock_account_state": MagicMock(return_value=_account()),
        "app._compute_trend": MagicMock(
            return_value={
                "direction": "bullish",
                "strength": "developing",
                "consecutive_count": 1,
                "last_signal": "buy",
                "flip_event": False,
                "confirmed_entry": False,
                "confirmed_exit": False,
                "bullish_candidate": False,
                "bearish_candidate": False,
                "previous_opposite_count": 0,
            }
        ),
        "app.is_fast_lane_buy_flip": MagicMock(return_value=False),
        "app._required_buy_confirmations": MagicMock(
            return_value={"required_buy_confirmations": 3, "reason": "test"}
        ),
    }) as env:
        with patch.object(_app, "ADAPTIVE_BUY_CONFIRMATION_ENABLED", True):
            _app.process_signal(_buy())
    assert_equal(env.rejection_category(), "trend_confirmation", "category")


def test_trend_confirmation_blocks_sell_non_bearish():
    """SELL where direction != bearish is rejected (no fast-lane)."""
    _fake_pos = MagicMock()
    with patch.object(_app.api, "get_position", return_value=_fake_pos):
        with _Env(**{
            "app.get_mock_account_state": MagicMock(return_value=_account()),
            "app._compute_trend": MagicMock(
                return_value={
                    "direction": "bullish",   # not bearish → sell confirmation fails
                    "strength": "confirmed",
                    "consecutive_count": 3,
                    "last_signal": "buy",
                    "flip_event": False,
                    "confirmed_entry": True,
                    "confirmed_exit": False,
                    "bullish_candidate": False,
                    "bearish_candidate": False,
                    "previous_opposite_count": 0,
                }
            ),
            "app.is_fast_lane_sell_flip": MagicMock(return_value=False),
            "app._required_sell_confirmations": MagicMock(
                return_value={"required_sell_confirmations": 2, "reason": "test"}
            ),
        }) as env:
            _app.process_signal(_sell())
    assert_equal(env.rejection_category(), "trend_confirmation", "category")


def test_fundamental_score_blocks_bearish_buy():
    """BUY blocked when pre-market bias flags a bearish fundamental score."""
    original = _app._market_bias.get(_SYMBOL)
    _app._market_bias[_SYMBOL] = {
        "bias": "neutral",
        "fundamental_score": "bearish",
        "risk_level": "high",
        "entry_quality": "neutral",
        "reason": "",
    }
    try:
        with _Env(**{
            "app.get_mock_account_state": MagicMock(return_value=_account()),
        }) as env:
            _app.process_signal(_buy())
        assert_equal(env.rejection_category(), "fundamental_score", "category")
    finally:
        if original is None:
            _app._market_bias.pop(_SYMBOL, None)
        else:
            _app._market_bias[_SYMBOL] = original


def test_chase_prevention_blocks_do_not_chase():
    """BUY blocked when entry_quality is do_not_chase."""
    original = _app._market_bias.get(_SYMBOL)
    _app._market_bias[_SYMBOL] = {
        "bias": "neutral",
        "fundamental_score": "neutral",
        "risk_level": "high",
        "entry_quality": "do_not_chase",
        "reason": "",
    }
    try:
        with _Env(**{
            "app.get_mock_account_state": MagicMock(return_value=_account()),
        }) as env:
            _app.process_signal(_buy())
        assert_equal(env.rejection_category(), "chase_prevention", "category")
    finally:
        if original is None:
            _app._market_bias.pop(_SYMBOL, None)
        else:
            _app._market_bias[_SYMBOL] = original


def test_sell_profit_threshold_blocks_small_profit_without_bearish_pressure():
    """SELL on a small-profit position is blocked without confirmed bearish trend."""
    exit_price = _PRICE * 1.002  # +0.2% → below 0.5% threshold
    existing_position = {"qty": 10, "current_price": exit_price, "avg_entry": _PRICE}
    _fake_pos = MagicMock()
    with patch.object(_app.api, "get_position", return_value=_fake_pos):
        with _Env(**{
            "app.get_position": MagicMock(return_value=existing_position),
            "app.get_mock_account_state": MagicMock(return_value=_account()),
            "app._compute_trend": MagicMock(
                return_value={
                    "direction": "neutral",
                    "strength": "weak",
                    "consecutive_count": 0,
                    "last_signal": None,
                    "flip_event": False,
                    "confirmed_entry": False,
                    "confirmed_exit": False,
                    "bullish_candidate": False,
                    "bearish_candidate": False,
                    "previous_opposite_count": 0,
                }
            ),
            "app.is_fast_lane_sell_flip": MagicMock(return_value=True),
        }) as env:
            _app.process_signal(_sell(price=exit_price))
    assert_equal(env.rejection_category(), "sell_profit_threshold", "category")


def test_sell_discipline_blocks_small_red_position_without_bearish():
    """SELL on a small-red position is blocked without confirmed bearish trend."""
    exit_price = _PRICE * 0.996  # -0.4% → in the [-0.75, 0) range
    existing_position = {"qty": 10, "current_price": exit_price, "avg_entry": _PRICE}
    _fake_pos = MagicMock()
    with patch.object(_app.api, "get_position", return_value=_fake_pos):
        with _Env(**{
            "app.get_position": MagicMock(return_value=existing_position),
            "app.get_mock_account_state": MagicMock(return_value=_account()),
            "app._compute_trend": MagicMock(
                return_value={
                    "direction": "neutral",
                    "strength": "weak",
                    "consecutive_count": 0,
                    "last_signal": None,
                    "flip_event": False,
                    "confirmed_entry": False,
                    "confirmed_exit": False,
                    "bullish_candidate": False,
                    "bearish_candidate": False,
                    "previous_opposite_count": 0,
                }
            ),
            "app.is_fast_lane_sell_flip": MagicMock(return_value=True),
        }) as env:
            _app.process_signal(_sell(price=exit_price))
    assert_equal(env.rejection_category(), "sell_discipline", "category")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

_TESTS = [
    # /webhook HTTP layer
    test_webhook_rejects_missing_secret,
    test_webhook_rejects_wrong_secret,
    test_webhook_rejects_non_json,
    test_webhook_rejects_invalid_action,
    test_webhook_rejects_unapproved_symbol,
    test_webhook_rejects_out_of_range_price,
    test_webhook_rejects_nonpositive_price,
    test_webhook_accepts_valid_buy_signal,
    # process_signal rejections
    test_ghost_sell_blocked_when_no_db_position,
    test_market_hours_blocks_outside_hours,
    test_circuit_breaker_blocks_buy_on_daily_loss,
    test_circuit_breaker_does_not_block_sell,
    test_duplicate_webhook_blocked,
    test_symbol_override_blocks_signal,
    test_cooldown_blocks_buy_within_window,
    test_churn_window_blocks_buy_after_recent_sell,
    test_churn_price_blocks_buy_near_last_sell_price,
    test_daily_symbol_buy_limit_blocks_at_max,
    test_session_trade_count_blocks_at_limit,
    test_exposure_cap_blocks_overexposed_buy,
    test_macro_risk_blocks_buy_when_regime_blocks,
    test_macro_position_limit_blocks_when_full,
    test_trend_confirmation_blocks_buy_insufficient_consecutive,
    test_trend_confirmation_blocks_sell_non_bearish,
    test_fundamental_score_blocks_bearish_buy,
    test_chase_prevention_blocks_do_not_chase,
    test_sell_profit_threshold_blocks_small_profit_without_bearish_pressure,
    test_sell_discipline_blocks_small_red_position_without_bearish,
]


def main():
    passed = 0
    failed = 0
    for fn in _TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} passed", "✓" if failed == 0 else f"  {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
