#!/usr/bin/env python3
"""
Trader Brain Ops Check.

Read-only readiness check for the observe-only trader-brain architecture.
"""

import json
from pathlib import Path
from market_intelligence.intraday_state import build_intraday_state
from market_intelligence.tape_reader import classify_tape
from config import APPROVED_SYMBOLS
from market_intelligence.market_state import load_market_context, macro_regime, symbol_context
from strategy.trade_scorer import score_trade
from db import DB_PATH, get_connection

def check_tape_smoke():
    print("\n── Tape Smoke Test ────────────────────────────────────")

    bars = []
    price = 100.0
    for i in range(30):
        price += 0.1
        bars.append({
            "h": price + 0.05,
            "l": price - 0.05,
            "c": price,
            "v": 1000 + i,
        })

    state = build_intraday_state("AAPL", bars)
    tape = classify_tape(state)

    print(f"symbol      : {state.get('symbol')}")
    print(f"bar_count   : {state.get('bar_count')}")
    print(f"trend_label : {state.get('trend_label')}")
    print(f"tape_label  : {tape.get('label')}")
    print(f"tape_score  : {tape.get('score')}")
    print(f"action_hint : {tape.get('action_hint')}")

    if state.get("bar_count") == 30 and tape.get("label"):
        ok("tape smoke test completed")
        return True

    fail("tape smoke test failed")
    return False

def ok(msg):
    print(f"[OK]   {msg}")


def warn(msg):
    print(f"[WARN] {msg}")


def fail(msg):
    print(f"[FAIL] {msg}")


def check_db_columns():
    print("\n── DB Columns ─────────────────────────────────────────")
    required = {
        "trader_brain_score",
        "trader_brain_setup_type",
        "trader_brain_approved",
        "trader_brain_reason",
        "trader_brain_positive_factors",
        "trader_brain_risk_factors",
    }

    with get_connection(DB_PATH) as con:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(trades)").fetchall()}

    missing = sorted(required - cols)
    if missing:
        fail(f"missing trader brain columns: {missing}")
        return False

    ok("all trader brain columns present")
    return True


def check_market_context():
    print("\n── Market Context ─────────────────────────────────────")
    ctx = load_market_context()
    symbols = ctx.get("symbols") or {}

    print(f"market_date     : {ctx.get('market_date')}")
    print(f"macro_regime    : {ctx.get('macro_regime')}")
    print(f"macro_sentiment : {ctx.get('macro_sentiment')}")
    print(f"source          : {ctx.get('source')}")

    missing = sorted(APPROVED_SYMBOLS - set(symbols))
    if missing:
        warn(f"market_context missing {len(missing)} approved symbols")
    else:
        ok(f"market_context has all approved symbols: {len(symbols)}")

    return True


def check_scorer_smoke():
    print("\n── Scorer Smoke Test ──────────────────────────────────")
    sample_symbols = ["AAPL", "SPY", "QQQ"]

    for sym in sample_symbols:
        if sym not in APPROVED_SYMBOLS:
            continue

        thesis = score_trade(
            symbol=sym,
            action="buy",
            trend={
                "direction": "bullish",
                "strength": "developing",
                "consecutive_count": 3,
            },
            momentum={
                "direction": "rising",
                "momentum_pct": 0.25,
                "premarket_alignment": "confirmed",
            },
            market_alignment={
                "benchmark": "QQQ" if sym != "SPY" else "SPY",
                "aligned_for_buy": True,
            },
        )

        print(
            f"{sym:<6} score={thesis.score:<5} "
            f"approved_by_scorer={thesis.approved_by_scorer} "
            f"setup={thesis.setup_type}"
        )

    ok("scorer smoke test completed")
    return True


def check_recent_scores():
    print("\n── Recent Stored Scores ───────────────────────────────")
    with get_connection(DB_PATH) as con:
        row = con.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN trader_brain_score IS NOT NULL THEN 1 ELSE 0 END) AS scored
            FROM trades
        """).fetchone()

    total = int(row["total"] or 0)
    scored = int(row["scored"] or 0)

    print(f"total trade rows : {total}")
    print(f"scored rows      : {scored}")

    if total and not scored:
        warn("no stored trader-brain scores yet; expected until live signals reach observe-only scorer")
    else:
        ok("stored score check completed")

    return True


def main():
    print("=" * 64)
    print("  Trader Brain Ops Check")
    print("=" * 64)

    checks = [
        check_db_columns(),
        check_market_context(),
        check_scorer_smoke(),
        check_tape_smoke(),
        check_recent_scores(),
    ]

    print()
    if all(checks):
        ok("trader brain ops check completed")
        return 0

    fail("one or more checks failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
