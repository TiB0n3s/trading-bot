#!/usr/bin/env python3
"""
Targeted tests for FIFO trade matching math.

These tests avoid touching trades.db. They validate the core FIFO behavior
with small in-memory examples.

Run:
  python3 tests/test_trade_matcher.py
"""

from collections import defaultdict, deque


def fifo_match(rows):
    """Small in-memory FIFO matcher for testing expected trade math.

    rows should be sorted ascending by timestamp/id and contain:
      symbol, action, qty, fill_price
    """
    lots = defaultdict(deque)
    matched = []

    for r in rows:
        sym = r["symbol"]
        action = r["action"].lower()
        qty = float(r["qty"])
        price = float(r["fill_price"])

        if action == "buy":
            lots[sym].append({"qty": qty, "price": price})
            continue

        if action == "sell":
            remaining = qty
            while remaining > 0 and lots[sym]:
                lot = lots[sym][0]
                matched_qty = min(remaining, lot["qty"])
                pnl = (price - lot["price"]) * matched_qty
                pnl_pct = ((price - lot["price"]) / lot["price"]) * 100 if lot["price"] else 0

                matched.append({
                    "symbol": sym,
                    "qty": matched_qty,
                    "entry_price": lot["price"],
                    "exit_price": price,
                    "realized_pnl": round(pnl, 4),
                    "realized_pnl_pct": round(pnl_pct, 4),
                })

                lot["qty"] -= matched_qty
                remaining -= matched_qty

                if lot["qty"] <= 0:
                    lots[sym].popleft()

    return matched, lots


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_single_lot_profit():
    matched, lots = fifo_match([
        {"symbol": "QQQ", "action": "buy", "qty": 2, "fill_price": 100},
        {"symbol": "QQQ", "action": "sell", "qty": 2, "fill_price": 105},
    ])

    assert_equal(len(matched), 1, "matched count")
    assert_equal(matched[0]["qty"], 2.0, "matched qty")
    assert_equal(matched[0]["realized_pnl"], 10.0, "pnl")
    assert_equal(round(matched[0]["realized_pnl_pct"], 2), 5.0, "pnl pct")
    assert_equal(len(lots["QQQ"]), 0, "open lots")


def test_partial_sell_leaves_open_lot():
    matched, lots = fifo_match([
        {"symbol": "NVDA", "action": "buy", "qty": 5, "fill_price": 200},
        {"symbol": "NVDA", "action": "sell", "qty": 2, "fill_price": 210},
    ])

    assert_equal(len(matched), 1, "matched count")
    assert_equal(matched[0]["qty"], 2.0, "matched qty")
    assert_equal(matched[0]["realized_pnl"], 20.0, "pnl")
    assert_equal(len(lots["NVDA"]), 1, "remaining lots")
    assert_equal(lots["NVDA"][0]["qty"], 3.0, "remaining qty")


def test_fifo_multiple_lots():
    matched, lots = fifo_match([
        {"symbol": "TSLA", "action": "buy", "qty": 1, "fill_price": 100},
        {"symbol": "TSLA", "action": "buy", "qty": 1, "fill_price": 110},
        {"symbol": "TSLA", "action": "sell", "qty": 2, "fill_price": 120},
    ])

    assert_equal(len(matched), 2, "matched count")
    assert_equal(matched[0]["entry_price"], 100.0, "first entry")
    assert_equal(matched[0]["realized_pnl"], 20.0, "first pnl")
    assert_equal(matched[1]["entry_price"], 110.0, "second entry")
    assert_equal(matched[1]["realized_pnl"], 10.0, "second pnl")
    assert_equal(len(lots["TSLA"]), 0, "open lots")


def test_unmatched_sell_does_not_create_short_lot():
    matched, lots = fifo_match([
        {"symbol": "IWM", "action": "sell", "qty": 2, "fill_price": 300},
    ])

    assert_equal(len(matched), 0, "matched count")
    assert_equal(len(lots["IWM"]), 0, "open lots")


def test_symbol_isolated_matching():
    matched, lots = fifo_match([
        {"symbol": "QQQ", "action": "buy", "qty": 1, "fill_price": 100},
        {"symbol": "SPY", "action": "buy", "qty": 1, "fill_price": 500},
        {"symbol": "QQQ", "action": "sell", "qty": 1, "fill_price": 101},
    ])

    assert_equal(len(matched), 1, "matched count")
    assert_equal(matched[0]["symbol"], "QQQ", "matched symbol")
    assert_equal(len(lots["QQQ"]), 0, "QQQ lots")
    assert_equal(len(lots["SPY"]), 1, "SPY lots remain")
    assert_equal(lots["SPY"][0]["qty"], 1.0, "SPY remaining qty")


def main():
    tests = [
        test_single_lot_profit,
        test_partial_sell_leaves_open_lot,
        test_fifo_multiple_lots,
        test_unmatched_sell_does_not_create_short_lot,
        test_symbol_isolated_matching,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} FIFO matcher tests passed.")


if __name__ == "__main__":
    main()
