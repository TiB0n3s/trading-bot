#!/usr/bin/env python3
"""Tests for the alpaca-py broker compatibility adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from alpaca_py_broker_adapter import AlpacaPyBrokerAdapter


class FakeTradingClient:
    def __init__(self):
        self.submitted = []
        self.cancelled = []

    def get_account(self):
        return SimpleNamespace(
            equity="10000", portfolio_value="10000", buying_power="5000", status="ACTIVE"
        )

    def get_open_position(self, symbol):
        return SimpleNamespace(
            symbol=symbol, qty="3", avg_entry_price="95", current_price="100", unrealized_pl="15"
        )

    def get_all_positions(self):
        return [self.get_open_position("AAPL")]

    def get_orders(self, filter=None):
        return [
            SimpleNamespace(
                id="order-1", symbol=filter.symbols[0], side="buy", qty="1", order_type="limit"
            )
        ]

    def cancel_order_by_id(self, order_id):
        self.cancelled.append(order_id)

    def get_order_by_id(self, order_id):
        return SimpleNamespace(id=order_id, status="filled")

    def submit_order(self, order_data):
        self.submitted.append(order_data)
        return SimpleNamespace(
            id="submitted-1", client_order_id=order_data.client_order_id, status="accepted"
        )


class FakeDataClient:
    def get_stock_latest_trade(self, request):
        return {request.symbol_or_symbols: SimpleNamespace(price="123.45")}

    def get_stock_latest_quote(self, request):
        return {
            request.symbol_or_symbols: SimpleNamespace(
                bid_price="123.40",
                ask_price="123.50",
            )
        }

    def get_stock_bars(self, request):
        return SimpleNamespace(
            data={
                request.symbol_or_symbols: [
                    SimpleNamespace(
                        open="100",
                        high="101",
                        low="99",
                        close="100.5",
                        volume="10000",
                    )
                ]
            }
        )


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_adapter_exposes_legacy_broker_methods():
    trading = FakeTradingClient()
    adapter = AlpacaPyBrokerAdapter(
        api_key="key",
        secret_key="secret",
        base_url="https://paper-api.alpaca.markets",
        trading_client=trading,
        data_client=FakeDataClient(),
    )

    account = adapter.get_account()
    position = adapter.get_position("aapl")
    trade = adapter.get_latest_trade("aapl")
    quote = adapter.get_latest_quote("aapl")
    bars = adapter.get_bars("aapl", "1Min", feed="iex")
    orders = adapter.list_orders(status="open", symbols=["aapl"])
    adapter.cancel_order("order-1")
    order = adapter.submit_order(
        symbol="aapl",
        qty=2,
        side="buy",
        type="market",
        time_in_force="day",
        order_class="bracket",
        stop_loss={"stop_price": 99.0},
        take_profit={"limit_price": 103.0},
        client_order_id="cid-1",
    )

    assert_equal(account.status, "ACTIVE", "account status")
    assert_equal(position.symbol, "AAPL", "position symbol")
    assert_equal(float(trade.price), 123.45, "latest trade price")
    assert_equal(float(quote.bid_price), 123.40, "latest quote bid")
    assert_equal(float(bars[0].close), 100.5, "bar close")
    assert_equal(orders[0].symbol, "AAPL", "order symbol")
    assert_equal(trading.cancelled, ["order-1"], "cancelled")
    assert_equal(order.id, "submitted-1", "submitted id")
    assert_equal(trading.submitted[0].client_order_id, "cid-1", "client order id")
    assert_equal(trading.submitted[0].order_class.value, "bracket", "order class")


def main():
    tests = [test_adapter_exposes_legacy_broker_methods]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} Alpaca-py broker adapter tests passed.")


if __name__ == "__main__":
    main()
