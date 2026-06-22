#!/usr/bin/env python3
"""Unit tests for broker input validation and order-flow boundaries."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
VENV_PYTHON = ROOT / "venv" / "bin" / "python"


def reexec_under_venv_if_available() -> None:
    if not VENV_PYTHON.exists():
        return
    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


reexec_under_venv_if_available()
os.environ.setdefault("ALPACA_API_KEY", "test-key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test-secret")
os.environ.setdefault("APCA_API_KEY_ID", "test-key")
os.environ.setdefault("APCA_API_SECRET_KEY", "test-secret")

import broker
from exceptions import ValidationError


class Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeApi:
    def __init__(self):
        self.submitted = []
        self.cancelled = []
        self.open_orders = []
        self.position_qty = 5

    def get_account(self):
        return Obj(cash="10000", portfolio_value="10000", buying_power="10000", status="ACTIVE")

    def get_latest_trade(self, symbol):
        return Obj(price="100")

    def get_latest_quote(self, symbol):
        return Obj(ask_price="101", bid_price="99")

    def get_position(self, symbol):
        return Obj(
            qty=str(self.position_qty),
            avg_entry_price="95",
            current_price="100",
            unrealized_pl="25",
        )

    def list_orders(self, status, symbols):
        return self.open_orders

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        self.open_orders = [o for o in self.open_orders if o.id != order_id]

    def submit_order(self, **kwargs):
        self.submitted.append(kwargs)
        return Obj(id="order-1", client_order_id=kwargs.get("client_order_id"), status="accepted")


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value, got {value!r}")


def assert_raises(exc_type, fn, label):
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"{label}: expected {exc_type.__name__}")


def with_fake_api(fn):
    original_api = broker.api
    original_is_cash_mode = broker.is_cash_mode
    fake = FakeApi()
    broker.api = fake
    broker.is_cash_mode = lambda: False
    try:
        fn(fake)
    finally:
        broker.api = original_api
        broker.is_cash_mode = original_is_cash_mode


def test_validate_order_request_normalizes_inputs():
    request = broker.validate_order_request(" aapl ", " BUY ", "1.5", "0.5", "1.5")
    assert_equal(request["symbol"], "AAPL", "symbol")
    assert_equal(request["action"], "buy", "action")
    assert_equal(request["position_size_pct"], 1.5, "position size")


def test_validate_order_request_allows_zero_position_size_for_sell():
    request = broker.validate_order_request("MA", "sell", 0, 0, 0)
    assert_equal(request["symbol"], "MA", "symbol")
    assert_equal(request["action"], "sell", "action")
    assert_equal(request["position_size_pct"], 0.0, "position size")


def test_validate_order_request_rejects_bad_action():
    assert_raises(
        ValidationError,
        lambda: broker.validate_order_request("AAPL", "hold", 1, 1, 1),
        "bad action",
    )


def test_place_order_buy_submits_bracket_order():
    def run(fake):
        result = broker.place_order("aapl", "buy", 2.0, 1.0, 3.0, client_order_id="cid-1")
        assert_true(result, "buy result")
        assert_equal(result["qty"], 2, "buy qty")
        assert_equal(result["side"], "buy", "buy side")
        assert_equal(len(fake.submitted), 1, "submitted count")
        submitted = fake.submitted[0]
        assert_equal(submitted["symbol"], "AAPL", "submitted symbol")
        assert_equal(submitted["order_class"], "bracket", "order class")
        assert_equal(submitted["stop_loss"], {"stop_price": 99.0}, "stop")
        assert_equal(submitted["take_profit"], {"limit_price": 103.0}, "take")

    with_fake_api(run)


def test_place_order_buy_too_small_does_not_submit():
    def run(fake):
        result = broker.place_order("AAPL", "buy", 0.001, 1.0, 3.0)
        assert_equal(result, None, "small result")
        assert_equal(len(fake.submitted), 0, "submitted count")

    with_fake_api(run)


def test_place_order_very_high_risk_halves_buy_qty():
    def run(fake):
        result = broker.place_order("AAPL", "buy", 4.0, 1.0, 3.0, risk_level="very_high")
        assert_true(result, "result")
        assert_equal(result["qty"], 2, "halved qty")

    with_fake_api(run)


def test_place_order_sell_closes_existing_position_without_bracket():
    def run(fake):
        fake.open_orders = [Obj(id="open-1", side="buy", qty="5", order_type="limit")]
        result = broker.place_order("AAPL", "sell", 0, 0, 0, qty_override=3)
        assert_true(result, "sell result")
        assert_equal(result["qty"], 3, "sell qty")
        assert_equal(result["side"], "sell", "sell side")
        assert_equal(fake.cancelled, ["open-1"], "cancelled")
        submitted = fake.submitted[0]
        assert_equal(submitted["side"], "sell", "submitted side")
        assert_true("order_class" not in submitted, "no bracket")

    with_fake_api(run)


def _with_broker_flags(**overrides):
    """Temporarily set broker module-level #16 flags."""
    saved = {key: getattr(broker, key) for key in overrides}

    def restore():
        for key, value in saved.items():
            setattr(broker, key, value)

    for key, value in overrides.items():
        setattr(broker, key, value)
    return restore


def test_buy_entry_reference_default_is_unchanged():
    # Flags off: assumed entry == last trade exactly (no behavior change). (#16)
    restore = _with_broker_flags(BROKER_ENTRY_SLIPPAGE_PCT=0.0, BROKER_USE_QUOTE_ANCHOR=False)
    try:
        assert_equal(broker._buy_entry_reference_price("AAPL", 100.0), 100.0, "default entry ref")
    finally:
        restore()


def test_buy_slippage_buffer_anchors_qty_and_brackets():
    # 0.10% buffer -> assumed entry 100.10; qty int(200/100.1)=1; brackets off 100.10. (#16)
    def run(fake):
        restore = _with_broker_flags(BROKER_ENTRY_SLIPPAGE_PCT=0.10, BROKER_USE_QUOTE_ANCHOR=False)
        try:
            result = broker.place_order("AAPL", "buy", 2.0, 1.0, 3.0)
        finally:
            restore()
        assert_equal(result["qty"], 1, "buffered qty")
        submitted = fake.submitted[0]
        assert_equal(submitted["stop_loss"], {"stop_price": 99.1}, "buffered stop")
        assert_equal(submitted["take_profit"], {"limit_price": 103.1}, "buffered take")

    with_fake_api(run)


def test_buy_quote_anchor_uses_ask():
    # Quote anchor on, slippage 0 -> assumed entry == ask (101); brackets off 101. (#16)
    def run(fake):
        restore = _with_broker_flags(BROKER_ENTRY_SLIPPAGE_PCT=0.0, BROKER_USE_QUOTE_ANCHOR=True)
        try:
            result = broker.place_order("AAPL", "buy", 4.0, 1.0, 3.0)
        finally:
            restore()
        # risk_amount=400 at ask 101 -> qty int(400/101)=3
        assert_equal(result["qty"], 3, "ask-anchored qty")
        submitted = fake.submitted[0]
        assert_equal(submitted["stop_loss"], {"stop_price": 99.99}, "ask-anchored stop")
        assert_equal(submitted["take_profit"], {"limit_price": 104.03}, "ask-anchored take")

    with_fake_api(run)


def main():
    tests = [
        test_validate_order_request_normalizes_inputs,
        test_validate_order_request_allows_zero_position_size_for_sell,
        test_validate_order_request_rejects_bad_action,
        test_place_order_buy_submits_bracket_order,
        test_place_order_buy_too_small_does_not_submit,
        test_place_order_very_high_risk_halves_buy_qty,
        test_place_order_sell_closes_existing_position_without_bracket,
        test_buy_entry_reference_default_is_unchanged,
        test_buy_slippage_buffer_anchors_qty_and_brackets,
        test_buy_quote_anchor_uses_ask,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} broker tests passed.")


if __name__ == "__main__":
    main()
