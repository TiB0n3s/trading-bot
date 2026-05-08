#!/usr/bin/env python3
"""
Position review — terminal-friendly open-position table.

Usage:
  python3 position_review.py
"""

import json
import os
import sys
import urllib.request


def money(v):
    if v is None:
        return "-"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}${float(v):,.2f}"


def pct(v):
    if v is None:
        return "-"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}{float(v):.2f}%"


def short(v, width):
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def main():
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        raise SystemExit("ERROR: WEBHOOK_SECRET not set. Run: set -a; source /etc/trading-bot.env; set +a")

    url = f"http://localhost:5000/positions?secret={secret}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise SystemExit(f"ERROR: Could not read /positions endpoint: {e}")

    summary = data.get("summary", {})
    positions = data.get("positions", [])

    print("=" * 132)
    print("  Position Review")
    print("=" * 132)
    print(f"  Positions        : {summary.get('total_positions')}/{summary.get('max_positions')}")
    print(f"  Account balance  : ${float(summary.get('account_balance') or 0):,.2f}")
    print(f"  Daily P&L %      : {summary.get('daily_pnl_pct')}")
    print(f"  Market date      : {summary.get('market_context_date')}")
    print(f"  Macro sentiment  : {summary.get('macro_sentiment')}")
    print()

    if not positions:
        print("No open positions.")
        return 0

    headers = [
        "Symbol", "Qty", "Value", "uP&L", "uP&L%", "Exp%",
        "HoldHr", "NowTrend", "NowBias", "EntryBias", "Risk", "EntryQual"
    ]

    widths = [6, 7, 12, 12, 8, 7, 8, 16, 9, 10, 10, 18]

    row_fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(row_fmt.format(*headers))
    print(row_fmt.format(*["-" * w for w in widths]))

    total_value = 0.0
    total_upl = 0.0

    for p in positions:
        value = float(p.get("market_value") or 0)
        upl = float(p.get("unrealized_pl") or 0)
        total_value += value
        total_upl += upl

        holding_minutes = p.get("holding_minutes")
        hold_hr = "-"
        if holding_minutes is not None:
            hold_hr = f"{float(holding_minutes) / 60:.1f}"

        now_trend = f"{p.get('trend_direction')}/{p.get('trend_strength')}"
        row = [
            p.get("symbol"),
            f"{float(p.get('qty') or 0):.2f}",
            f"${value:,.2f}",
            money(upl),
            pct(p.get("unrealized_pl_pct")),
            f"{float(p.get('exposure_pct') or 0):.2f}",
            hold_hr,
            short(now_trend, 16),
            short(p.get("market_bias"), 9),
            short(p.get("entry_market_bias"), 10),
            short(p.get("entry_risk_level"), 10),
            short(p.get("entry_quality"), 18),
        ]

        print(row_fmt.format(*row))

    print(row_fmt.format(*["-" * w for w in widths]))
    print(f"{'TOTAL':<14} {'$' + format(total_value, ',.2f'):<12} {money(total_upl):<12}")

    print()
    print("Notes:")
    print("  NowTrend/NowBias are current state.")
    print("  EntryBias/Risk/EntryQual come from the oldest currently-open FIFO lot.")
    print("  Null/blank entry fields usually mean the lot predates attribution tracking.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
