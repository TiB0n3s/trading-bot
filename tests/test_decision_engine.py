#!/usr/bin/env python3
"""
Tests for decision_engine.evaluate_signal and _get_symbol_history.

Coverage:
  evaluate_signal:
    happy path valid JSON response
    JSON parse error → fail-open rejection
    API exception → fail-open rejection
    assistant prefill `{` present in messages list
    trailing junk after closing `}` still fails-closed gracefully
    diagnostic key removal before API call
    symbol_history injected for BUY signals
    symbol_history NOT injected for SELL signals
    None account_state handled safely
    Claude called with correct model name
    timeout is configured
    system is a content-block list with cache_control

  _get_symbol_history:
    no rows → {"sample_size": 0}
    rows with wins/losses → correct aggregates
    per-setup win rate when trend context provided
    per-setup win rate absent when only 1 matching row
    per-setup win rate absent when no trend context passed
    DB exception → {"sample_size": 0} fail-open
    null pnl/holding values handled without crash
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ALPACA_API_KEY", "test-key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import decision_engine as _de

# _client is lazily initialised on first real API call, so it is None at import
# time. seed it with a MagicMock so that patch.object(_de._client.messages, …)
# has a real object to target in every test.
_de._client = MagicMock()

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_equal(actual, expected, label=""):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label=""):
    if not value:
        raise AssertionError(f"{label}: expected truthy, got {value!r}")


def assert_false(value, label=""):
    if value:
        raise AssertionError(f"{label}: expected falsy, got {value!r}")


def assert_in(value, container, label=""):
    if value not in container:
        raise AssertionError(f"{label}: {value!r} not in {container!r}")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_RESPONSE = {
    "approved": True,
    "reason": "bullish confirmed trend with strong momentum",
    "position_size_pct": 2.5,
    "stop_loss_pct": 1.75,
    "take_profit_pct": 0,
    "confidence": "high",
}

# The model completes after the `{` prefill, so the mock text is everything after the
# opening brace — the full JSON minus its first character.
_VALID_RESPONSE_TEXT = json.dumps(_VALID_RESPONSE)[1:]


def _mock_message(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def _capture_create(response_text: str):
    """Returns (fake_create fn, captured dict). captured["kwargs"] set on first call."""
    captured = {}

    def fake_create(**kwargs):
        captured["kwargs"] = kwargs
        return _mock_message(response_text)

    return fake_create, captured


# ---------------------------------------------------------------------------
# evaluate_signal — response parsing
# ---------------------------------------------------------------------------

def test_evaluate_signal_happy_path():
    with patch.object(_de._client.messages, "create",
                      return_value=_mock_message(_VALID_RESPONSE_TEXT)):
        with patch.object(_de, "_get_symbol_history", return_value={"sample_size": 0}):
            result = _de.evaluate_signal(
                {"action": "buy", "symbol": "AAPL", "price": 200.0},
                {"balance": 100_000.0},
            )
    assert_equal(result["approved"], True, "approved")
    assert_equal(result["confidence"], "high", "confidence")
    assert_equal(result["position_size_pct"], 2.5, "position_size_pct")
    assert_equal(result["stop_loss_pct"], 1.75, "stop_loss_pct")
    assert_equal(result["take_profit_pct"], 0, "take_profit_pct")


def test_evaluate_signal_json_parse_error_rejects_safely():
    with patch.object(_de._client.messages, "create",
                      return_value=_mock_message("not valid json {")):
        result = _de.evaluate_signal(
            {"action": "buy", "symbol": "AAPL", "price": 200.0},
            {},
        )
    assert_equal(result["approved"], False, "approved on parse error")
    assert_in("Parse error", result["reason"], "reason")
    assert_equal(result["position_size_pct"], 0, "position_size_pct")
    assert_equal(result["stop_loss_pct"], 1.75, "stop_loss_pct safe default")
    assert_equal(result["confidence"], "low", "confidence")


def test_evaluate_signal_api_exception_rejects_safely():
    with patch.object(_de._client.messages, "create",
                      side_effect=Exception("connection refused")):
        result = _de.evaluate_signal(
            {"action": "buy", "symbol": "AAPL", "price": 200.0},
            {},
        )
    assert_equal(result["approved"], False, "approved on API error")
    assert_in("Engine error", result["reason"], "reason")
    assert_equal(result["position_size_pct"], 0, "position_size_pct")
    assert_equal(result["stop_loss_pct"], 1.75, "stop_loss_pct")
    assert_equal(result["confidence"], "low", "confidence")


def test_evaluate_signal_prefill_in_messages():
    """Assistant prefill { must be the second message sent to the API."""
    fake_create, captured = _capture_create(_VALID_RESPONSE_TEXT)
    with patch.object(_de._client.messages, "create", side_effect=fake_create):
        with patch.object(_de, "_get_symbol_history", return_value={"sample_size": 0}):
            _de.evaluate_signal({"action": "buy", "symbol": "AAPL", "price": 200.0}, {})

    msgs = captured["kwargs"]["messages"]
    assert_equal(len(msgs), 2, "two messages: user + assistant prefill")
    assert_equal(msgs[1]["role"], "assistant", "second message is assistant")
    assert_equal(msgs[1]["content"], "{", "prefill content is opening brace")


def test_evaluate_signal_trailing_junk_rejects_safely():
    """Trailing prose after the closing } is still caught by JSON parse fail-closed."""
    junk_completion = _VALID_RESPONSE_TEXT + "\n\nSome unexpected trailing text."
    with patch.object(_de._client.messages, "create",
                      return_value=_mock_message(junk_completion)):
        with patch.object(_de, "_get_symbol_history", return_value={"sample_size": 0}):
            result = _de.evaluate_signal(
                {"action": "buy", "symbol": "AAPL", "price": 200.0},
                {},
            )
    assert_equal(result["approved"], False, "approved is False on trailing junk")
    assert_in("Parse error", result["reason"], "reason mentions parse error")


# ---------------------------------------------------------------------------
# evaluate_signal — account_state preprocessing
# ---------------------------------------------------------------------------

def test_evaluate_signal_removes_diagnostic_keys():
    fake_create, captured = _capture_create(_VALID_RESPONSE_TEXT)
    with patch.object(_de._client.messages, "create", side_effect=fake_create):
        with patch.object(_de, "_get_symbol_history", return_value={"sample_size": 0}):
            _de.evaluate_signal(
                {"action": "buy", "symbol": "AAPL", "price": 200.0},
                {
                    "balance": 100_000.0,
                    "adaptive_buy_confirmation": {"some": "data"},
                    "adaptive_buy_confirmation_error": "some error",
                    "market_alignment": {"more": "data"},
                    "market_alignment_error": "err",
                },
            )

    prompt = captured["kwargs"]["messages"][0]["content"]
    account_json = prompt[prompt.index("Account: ") + len("Account: "):]
    account_dict = json.loads(account_json)

    for key in ("adaptive_buy_confirmation", "adaptive_buy_confirmation_error",
                "market_alignment", "market_alignment_error"):
        assert_false(key in account_dict, f"{key} must be stripped from account_state")


def test_evaluate_signal_preserves_non_diagnostic_keys():
    fake_create, captured = _capture_create(_VALID_RESPONSE_TEXT)
    with patch.object(_de._client.messages, "create", side_effect=fake_create):
        with patch.object(_de, "_get_symbol_history", return_value={"sample_size": 0}):
            _de.evaluate_signal(
                {"action": "buy", "symbol": "AAPL", "price": 200.0},
                {"balance": 100_000.0, "open_position_count": 3},
            )

    prompt = captured["kwargs"]["messages"][0]["content"]
    account_json = prompt[prompt.index("Account: ") + len("Account: "):]
    account_dict = json.loads(account_json)

    assert_in("balance", account_dict, "balance preserved")
    assert_in("open_position_count", account_dict, "open_position_count preserved")


def test_evaluate_signal_injects_symbol_history_for_buy():
    fake_create, captured = _capture_create(_VALID_RESPONSE_TEXT)
    with patch.object(_de._client.messages, "create", side_effect=fake_create):
        with patch.object(_de, "_get_symbol_history",
                          return_value={"sample_size": 3, "win_rate": 0.667}) as mock_hist:
            _de.evaluate_signal(
                {"action": "buy", "symbol": "AAPL", "price": 200.0},
                {"balance": 100_000.0},
            )
            mock_hist.assert_called_once()

    prompt = captured["kwargs"]["messages"][0]["content"]
    account_json = prompt[prompt.index("Account: ") + len("Account: "):]
    account_dict = json.loads(account_json)
    assert_in("symbol_history", account_dict, "symbol_history injected for BUY")
    assert_equal(account_dict["symbol_history"]["sample_size"], 3, "sample_size in symbol_history")


def test_evaluate_signal_no_symbol_history_for_sell():
    fake_create, captured = _capture_create(_VALID_RESPONSE_TEXT)
    with patch.object(_de._client.messages, "create", side_effect=fake_create):
        with patch.object(_de, "_get_symbol_history") as mock_hist:
            _de.evaluate_signal(
                {"action": "sell", "symbol": "AAPL", "price": 200.0},
                {"balance": 100_000.0},
            )
            mock_hist.assert_not_called()

    prompt = captured["kwargs"]["messages"][0]["content"]
    account_json = prompt[prompt.index("Account: ") + len("Account: "):]
    account_dict = json.loads(account_json)
    assert_false("symbol_history" in account_dict, "symbol_history absent for SELL")


def test_evaluate_signal_none_account_state_safe():
    with patch.object(_de._client.messages, "create",
                      return_value=_mock_message(_VALID_RESPONSE_TEXT)):
        with patch.object(_de, "_get_symbol_history", return_value={"sample_size": 0}):
            result = _de.evaluate_signal(
                {"action": "buy", "symbol": "AAPL", "price": 200.0},
                None,
            )
    assert_equal(result["approved"], True, "approved with None account_state")


# ---------------------------------------------------------------------------
# evaluate_signal — API call parameters
# ---------------------------------------------------------------------------

def test_evaluate_signal_uses_haiku_model():
    fake_create, captured = _capture_create(_VALID_RESPONSE_TEXT)
    with patch.object(_de._client.messages, "create", side_effect=fake_create):
        with patch.object(_de, "_get_symbol_history", return_value={"sample_size": 0}):
            _de.evaluate_signal({"action": "buy", "symbol": "AAPL", "price": 200.0}, {})

    assert_equal(captured["kwargs"]["model"], "claude-haiku-4-5-20251001", "model")


def test_evaluate_signal_timeout_configured():
    fake_create, captured = _capture_create(_VALID_RESPONSE_TEXT)
    with patch.object(_de._client.messages, "create", side_effect=fake_create):
        with patch.object(_de, "_get_symbol_history", return_value={"sample_size": 0}):
            _de.evaluate_signal({"action": "buy", "symbol": "AAPL", "price": 200.0}, {})

    timeout = captured["kwargs"].get("timeout")
    assert_true(timeout is not None, "timeout must be set")
    assert_true(timeout <= 15.0, f"timeout should be ≤ 15s, got {timeout}")


def test_evaluate_signal_system_prompt_set():
    fake_create, captured = _capture_create(_VALID_RESPONSE_TEXT)
    with patch.object(_de._client.messages, "create", side_effect=fake_create):
        with patch.object(_de, "_get_symbol_history", return_value={"sample_size": 0}):
            _de.evaluate_signal({"action": "buy", "symbol": "AAPL", "price": 200.0}, {})

    system = captured["kwargs"].get("system")
    assert_true(isinstance(system, list) and len(system) == 1, "system is a single-block list")
    block = system[0]
    assert_equal(block.get("type"), "text", "system block type is text")
    assert_true(len(block.get("text", "")) > 100, "system block text is non-trivial")
    assert_equal(block.get("cache_control"), {"type": "ephemeral"}, "cache_control is ephemeral")


# ---------------------------------------------------------------------------
# _get_symbol_history
# ---------------------------------------------------------------------------

def _make_row(won, pnl_pct, holding_min, direction="bullish", strength="confirmed"):
    return {
        "won": won,
        "realized_pnl_pct": pnl_pct,
        "holding_minutes": holding_min,
        "trend_direction": direction,
        "trend_strength": strength,
    }


def _patch_db(rows):
    """Stub trades_repo.recent_symbol_outcomes to return fixture rows."""
    return patch("repositories.trades_repo.recent_symbol_outcomes", return_value=rows)


def test_symbol_history_no_rows():
    with _patch_db([]):
        result = _de._get_symbol_history("AAPL")
    assert_equal(result, {"sample_size": 0}, "empty history")


def test_symbol_history_aggregates_wins_and_losses():
    rows = [
        _make_row(won=True,  pnl_pct=2.0,  holding_min=30),
        _make_row(won=True,  pnl_pct=1.5,  holding_min=45),
        _make_row(won=False, pnl_pct=-1.0, holding_min=20),
    ]
    with _patch_db(rows):
        result = _de._get_symbol_history("AAPL")

    assert_equal(result["sample_size"], 3, "sample_size")
    assert_equal(result["win_rate"], round(2 / 3, 3), "win_rate")
    assert_equal(result["avg_win_pct"], round((2.0 + 1.5) / 2, 3), "avg_win_pct")
    assert_equal(result["avg_loss_pct"], -1.0, "avg_loss_pct")
    assert_equal(result["avg_holding_minutes"], round((30 + 45 + 20) / 3), "avg_holding_minutes")
    assert_equal(result["last_5_outcomes"], ["win", "win", "loss"], "last_5_outcomes")


def test_symbol_history_last_5_outcomes_capped():
    rows = [_make_row(won=(i % 2 == 0), pnl_pct=1.0 if i % 2 == 0 else -1.0,
                      holding_min=30) for i in range(10)]
    with _patch_db(rows):
        result = _de._get_symbol_history("AAPL")
    assert_equal(len(result["last_5_outcomes"]), 5, "last_5_outcomes capped at 5")


def test_symbol_history_per_setup_win_rate():
    rows = [
        _make_row(won=True,  pnl_pct=2.0,  holding_min=30, direction="bullish", strength="confirmed"),
        _make_row(won=True,  pnl_pct=1.5,  holding_min=45, direction="bullish", strength="confirmed"),
        _make_row(won=False, pnl_pct=-1.0, holding_min=20, direction="bearish", strength="weak"),
    ]
    with _patch_db(rows):
        result = _de._get_symbol_history("AAPL", trend_direction="bullish", trend_strength="confirmed")

    assert_equal(result["current_setup_win_rate"], 1.0, "current_setup_win_rate")
    assert_equal(result["current_setup_sample"], 2, "current_setup_sample")


def test_symbol_history_per_setup_absent_when_only_one_match():
    rows = [
        _make_row(won=True,  pnl_pct=2.0,  holding_min=30, direction="bullish", strength="confirmed"),
        _make_row(won=False, pnl_pct=-1.0, holding_min=20, direction="bearish", strength="weak"),
    ]
    with _patch_db(rows):
        result = _de._get_symbol_history("AAPL", trend_direction="bullish", trend_strength="confirmed")

    assert_false("current_setup_win_rate" in result,
                 "current_setup_win_rate absent when < 2 matching setup rows")


def test_symbol_history_per_setup_absent_without_trend_context():
    rows = [
        _make_row(won=True,  pnl_pct=2.0,  holding_min=30),
        _make_row(won=False, pnl_pct=-1.0, holding_min=20),
    ]
    with _patch_db(rows):
        result = _de._get_symbol_history("AAPL")

    assert_false("current_setup_win_rate" in result,
                 "current_setup_win_rate absent when no trend context passed")


def test_symbol_history_db_exception_fail_open():
    with patch("repositories.trades_repo.recent_symbol_outcomes", side_effect=Exception("db locked")):
        result = _de._get_symbol_history("AAPL")
    assert_equal(result, {"sample_size": 0}, "fail-open on DB exception")


def test_symbol_history_handles_null_pnl_and_holding():
    rows = [
        {"won": True,  "realized_pnl_pct": None, "holding_minutes": None,
         "trend_direction": "bullish", "trend_strength": "confirmed"},
        {"won": False, "realized_pnl_pct": None, "holding_minutes": None,
         "trend_direction": "bullish", "trend_strength": "confirmed"},
    ]
    with _patch_db(rows):
        result = _de._get_symbol_history("AAPL")

    assert_equal(result["sample_size"], 2, "sample_size")
    assert_equal(result["avg_win_pct"], None, "avg_win_pct is None when no non-null wins")
    assert_equal(result["avg_loss_pct"], None, "avg_loss_pct is None when no non-null losses")
    assert_equal(result["avg_holding_minutes"], None, "avg_holding_minutes is None")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main():
    tests = [
        test_evaluate_signal_happy_path,
        test_evaluate_signal_json_parse_error_rejects_safely,
        test_evaluate_signal_api_exception_rejects_safely,
        test_evaluate_signal_prefill_in_messages,
        test_evaluate_signal_trailing_junk_rejects_safely,
        test_evaluate_signal_removes_diagnostic_keys,
        test_evaluate_signal_preserves_non_diagnostic_keys,
        test_evaluate_signal_injects_symbol_history_for_buy,
        test_evaluate_signal_no_symbol_history_for_sell,
        test_evaluate_signal_none_account_state_safe,
        test_evaluate_signal_uses_haiku_model,
        test_evaluate_signal_timeout_configured,
        test_evaluate_signal_system_prompt_set,
        test_symbol_history_no_rows,
        test_symbol_history_aggregates_wins_and_losses,
        test_symbol_history_last_5_outcomes_capped,
        test_symbol_history_per_setup_win_rate,
        test_symbol_history_per_setup_absent_when_only_one_match,
        test_symbol_history_per_setup_absent_without_trend_context,
        test_symbol_history_db_exception_fail_open,
        test_symbol_history_handles_null_pnl_and_holding,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"[OK] {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1

    print()
    if failed:
        print(f"{passed} passed, {failed} FAILED.")
        sys.exit(1)
    else:
        print(f"All {passed} decision_engine tests passed.")


if __name__ == "__main__":
    main()
