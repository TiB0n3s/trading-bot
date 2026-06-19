#!/usr/bin/env python3
"""
Attribution Report.

Read-only report for matched trade outcomes grouped by decision context.

Usage:
  python3 attribution_report.py
  python3 attribution_report.py --date 2026-05-26
  python3 attribution_report.py --all
"""

import argparse
from datetime import date

from analytics_ext.attribution import attribution_summary


def print_group(title, group):
    print()
    print(f"── {title} " + "─" * max(0, 60 - len(title)))

    if not group:
        print("  (none)")
        return

    print(f"  {'Key':<30} {'Trades':>6} {'P&L':>10} {'Win%':>7} {'Exp':>9} {'PF':>8}")
    print(f"  {'-'*30} {'-'*6} {'-'*10} {'-'*7} {'-'*9} {'-'*8}")

    for key, stats in sorted(
        group.items(),
        key=lambda x: (x[1].get("trades", 0), x[1].get("pnl", 0)),
        reverse=True,
    ):
        pf = stats.get("profit_factor")
        pf_str = str(pf) if pf is not None else "-"
        print(
            f"  {str(key)[:30]:<30} "
            f"{stats.get('trades', 0):>6} "
            f"{stats.get('pnl', 0):>10.2f} "
            f"{stats.get('win_rate', 0):>6.1f}% "
            f"{stats.get('expectancy', 0):>9.2f} "
            f"{pf_str:>8}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Date YYYY-MM-DD, default=today")
    parser.add_argument("--all", action="store_true", help="All matched trades")
    args = parser.parse_args()

    date_prefix = None if args.all else (args.date or date.today().isoformat())
    summary = attribution_summary(date_prefix=date_prefix)

    print("=" * 72)
    print("  Attribution Report")
    print("=" * 72)
    print(f"date_prefix : {summary.get('date_prefix')}")

    overall = summary.get("overall") or {}

    print()
    print("── Overall ────────────────────────────────────────────")
    print(f"  Trades        : {overall.get('trades', 0)}")
    print(f"  P&L           : ${overall.get('pnl', 0):+.2f}")
    print(f"  Wins/Losses   : {overall.get('wins', 0)}W / {overall.get('losses', 0)}L / {overall.get('flats', 0)}F")
    print(f"  Win rate      : {overall.get('win_rate', 0):.1f}%")
    print(f"  Expectancy    : ${overall.get('expectancy', 0):+.2f}")
    print(f"  Profit factor : {overall.get('profit_factor') or '-'}")

    by_field = summary.get("by_field") or {}

    for field in [
        "symbol",
        "macro_regime",
        "market_bias",
        "risk_level",
        "entry_quality",
        "trend_direction",
        "trend_strength",
        "trader_brain_setup_type",
        "trader_brain_approved",
    ]:
        print_group(field, by_field.get(field, {}))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
