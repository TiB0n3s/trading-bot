#!/usr/bin/env python3
"""
Drawdown attribution report — read-only.

Usage:
  python3 drawdown_report.py
  python3 drawdown_report.py 2026-05-08
"""

import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from broker import api
from trade_matcher import rebuild_matched_trades

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "trades.db"


def money(v):
    sign = "+" if v >= 0 else ""
    return f"{sign}${v:,.2f}"


def pct(v):
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

    print("=" * 72)
    print(f"  Drawdown Attribution Report — {target_date}")
    print("=" * 72)

    try:
        rebuild_matched_trades()
    except Exception as e:
        print(f"[WARN] matched_trades rebuild failed: {e}")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    matched = con.execute("""
        SELECT symbol, qty, entry_price, exit_price, realized_pnl, realized_pnl_pct,
               entry_timestamp, exit_timestamp, trend_direction, trend_strength,
               market_bias, risk_level, entry_quality
        FROM matched_trades
        WHERE exit_timestamp LIKE ?
        ORDER BY realized_pnl ASC
    """, (f"{target_date}%",)).fetchall()

    realized_by_symbol = defaultdict(float)
    for r in matched:
        realized_by_symbol[r["symbol"]] += float(r["realized_pnl"] or 0)

    con.close()

    print()
    print("── Realized P&L by Symbol ─────────────────────────────")
    if realized_by_symbol:
        total_realized = sum(realized_by_symbol.values())
        for sym, pnl in sorted(realized_by_symbol.items(), key=lambda x: x[1]):
            print(f"  {sym:<6} {money(pnl):>12}")
        print(f"  {'TOTAL':<6} {money(total_realized):>12}")
    else:
        total_realized = 0.0
        print("  No matched closed trades for this date.")

    print()
    print("── Worst Closed Trades ────────────────────────────────")
    if matched:
        for r in matched[:10]:
            print(
                f"  {r['symbol']:<6} qty={r['qty']:<5} "
                f"{r['entry_price']:.2f} → {r['exit_price']:.2f} "
                f"P&L={money(float(r['realized_pnl'] or 0)):>10} "
                f"trend={r['trend_direction']}/{r['trend_strength']} "
                f"bias={r['market_bias']} risk={r['risk_level']} entry={r['entry_quality']}"
            )
    else:
        print("  No closed trades.")

    print()
    print("── Current Unrealized P&L by Alpaca Position ──────────")

    unrealized = []
    try:
        positions = api.list_positions()
        for p in positions:
            qty = float(p.qty)
            avg = float(p.avg_entry_price)
            cur = float(p.current_price)
            mv = float(p.market_value)
            upl = float(p.unrealized_pl)
            upl_pct = float(p.unrealized_plpc) * 100
            unrealized.append({
                "symbol": p.symbol,
                "qty": qty,
                "avg": avg,
                "cur": cur,
                "market_value": mv,
                "unrealized_pl": upl,
                "unrealized_pct": upl_pct,
            })
    except Exception as e:
        print(f"  [FAIL] Could not fetch Alpaca positions: {e}")
        unrealized = []

    if unrealized:
        total_unrealized = sum(p["unrealized_pl"] for p in unrealized)
        for p in sorted(unrealized, key=lambda x: x["unrealized_pl"]):
            print(
                f"  {p['symbol']:<6} qty={p['qty']:<7.2f} "
                f"avg={p['avg']:<9.2f} cur={p['cur']:<9.2f} "
                f"uP&L={money(p['unrealized_pl']):>12} "
                f"({pct(p['unrealized_pct'])}) "
                f"value=${p['market_value']:,.2f}"
            )
        print(f"  {'TOTAL':<6} {'':<36} uP&L={money(total_unrealized):>12}")
    else:
        total_unrealized = 0.0
        print("  No open Alpaca positions.")

    print()
    print("── Daily P&L Attribution ──────────────────────────────")
    total_daily = total_realized + total_unrealized
    print(f"  Realized P&L   : {money(total_realized)}")
    print(f"  Unrealized P&L : {money(total_unrealized)}")
    print(f"  Estimated total: {money(total_daily)}")

    print()
    print("── Notes ──────────────────────────────────────────────")
    print("  Realized P&L comes from matched_trades FIFO exits for the target date.")
    print("  Unrealized P&L comes live from Alpaca current positions.")
    print("  This report is read-only and does not place/cancel/modify orders.")


if __name__ == "__main__":
    main()
