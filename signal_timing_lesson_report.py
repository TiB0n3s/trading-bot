#!/usr/bin/env python3
"""
Signal timing lesson report — read-only.

Uses historical_signal_outcomes to produce deterministic timing lessons.

This does not modify trading behavior.

Usage:
  python3 signal_timing_lesson_report.py
  python3 signal_timing_lesson_report.py --symbol AAPL
  python3 signal_timing_lesson_report.py --date 2026-05-22
  python3 signal_timing_lesson_report.py --details
"""

import argparse

from repositories.reporting_repo import ReportingRepository

repo = ReportingRepository()


def money(v):
    if v is None:
        return "-"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}${float(v):.2f}"


def pct(v):
    if v is None:
        return "-"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}{float(v):.2f}%"


def num(v, digits=1):
    if v is None:
        return "-"
    return f"{float(v):.{digits}f}"


def short(v, width):
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def recommendation(row):
    action = row["action"]
    bucket = row["bucket"]
    n = int(row["n"] or 0)
    matched = int(row["matched"] or 0)
    avg_pnl = float(row["avg_pnl"] or 0)
    total_pnl = float(row["total_pnl"] or 0)
    avg_delay = row["avg_entry_delay"]

    if matched < 3:
        return "watch_more_data"

    if action == "buy":
        if "immediate_entry" in str(bucket) and avg_pnl > 0:
            return "allow_immediate_if_context_confirms"
        if "immediate_entry" in str(bucket) and avg_pnl < 0:
            return "avoid_immediate_entry_or_require_confirmation"
        if "delayed_entry" in str(bucket) and avg_pnl > 0:
            return "prefer_wait_for_confirmation"
        if "very_late_entry" in str(bucket) and avg_pnl < 0:
            return "avoid_late_chasing"
        if total_pnl > 0:
            return "setup_has_positive_expectancy"
        return "setup_needs_caution"

    if action == "sell":
        if "immediate_exit" in str(bucket) and avg_pnl > 0:
            return "sell_signal_exit_timing_good"
        if "delayed_exit" in str(bucket) and avg_pnl < 0:
            return "consider_faster_exit"
        if total_pnl > 0:
            return "sell_context_generally_profitable"
        return "sell_context_needs_review"

    return "review"


def fetch_rows(group_expr, where_sql, params):
    return repo.timing_lesson_rows(group_expr, where_sql, params)


def print_lesson_table(title, rows):
    print()
    print(f"── {title} " + "─" * max(0, 98 - len(title)))

    if not rows:
        print("  No rows.")
        return

    headers = [
        "Bucket", "Act", "N", "Match", "Win", "Loss",
        "AvgEnt", "AvgExit", "AvgHold", "AvgP&L", "TotP&L", "Avg%", "Recommendation"
    ]
    widths = [28, 5, 5, 6, 5, 5, 8, 8, 8, 9, 9, 8, 40]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for r in rows:
        print(fmt.format(
            short(r["bucket"], 28),
            short(r["action"], 5),
            r["n"],
            r["matched"],
            r["winners"],
            r["losers"],
            num(r["avg_entry_delay"], 1),
            num(r["avg_exit_delay"], 1),
            num(r["avg_holding_minutes"], 1),
            money(r["avg_pnl"]),
            money(r["total_pnl"]),
            pct(r["avg_pnl_pct"]),
            short(recommendation(r), 40),
        ))


def print_details(where_sql, params):
    rows = repo.timing_lesson_detail_rows(where_sql, params)

    print()
    print("── Details ─────────────────────────────────────────────────────────────")

    if not rows:
        print("  No details.")
        return

    print(
        f"  {'Date':<10} {'Sym':<6} {'Act':<5} {'SigTime':<19} "
        f"{'EntDelay':>8} {'ExitDelay':>9} {'P&L':>9} "
        f"{'EntryLabel':<20} {'Learning':<28} Reason"
    )
    print(
        f"  {'-'*10} {'-'*6} {'-'*5} {'-'*19} "
        f"{'-'*8} {'-'*9} {'-'*9} "
        f"{'-'*20} {'-'*28} {'-'*50}"
    )

    for r in rows:
        print(
            f"  {short(r['market_date'], 10):<10} "
            f"{short(r['symbol'], 6):<6} "
            f"{short(r['action'], 5):<5} "
            f"{short(r['signal_timestamp'], 19):<19} "
            f"{num(r['entry_delay_minutes'], 1):>8} "
            f"{num(r['exit_delay_minutes'], 1):>9} "
            f"{money(r['realized_pnl']):>9} "
            f"{short(r['entry_timing_label'], 20):<20} "
            f"{short(r['learning_label'], 28):<28} "
            f"{short(r['learning_reason'], 80)}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--symbol")
    parser.add_argument("--action", choices=["buy", "sell"])
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()

    where = ["1=1"]
    params = []

    if args.date:
        where.append("market_date = ?")
        params.append(args.date)

    if args.symbol:
        where.append("symbol = ?")
        params.append(args.symbol.upper())

    if args.action:
        where.append("action = ?")
        params.append(args.action)

    where_sql = " AND ".join(where)

    summary = repo.timing_lesson_summary(where_sql, params)

    by_symbol = fetch_rows("symbol", where_sql, params)
    by_entry = fetch_rows("entry_timing_label", where_sql, params)
    by_exit = fetch_rows("exit_timing_label", where_sql, params)
    by_learning = fetch_rows("learning_label", where_sql, params)
    by_symbol_entry = fetch_rows("symbol || ':' || entry_timing_label", where_sql, params)

    print("=" * 132)
    print("  Signal Timing Lesson Report")
    print("=" * 132)

    if args.date:
        print(f"  date   : {args.date}")
    if args.symbol:
        print(f"  symbol : {args.symbol.upper()}")
    if args.action:
        print(f"  action : {args.action}")

    print()
    print("Summary")
    print("-------")
    print(f"  Signals          : {summary['signals'] or 0}")
    print(f"  Matched          : {summary['matched'] or 0}")
    print(f"  Winners          : {summary['winners'] or 0}")
    print(f"  Losers           : {summary['losers'] or 0}")
    print(f"  Avg entry delay  : {num(summary['avg_entry_delay'], 1)} min")
    print(f"  Avg exit delay   : {num(summary['avg_exit_delay'], 1)} min")
    print(f"  Total P&L        : {money(summary['total_pnl'])}")
    print(f"  Avg P&L          : {money(summary['avg_pnl'])}")
    print(f"  Avg P&L%         : {pct(summary['avg_pnl_pct'])}")

    print_lesson_table("By Symbol", by_symbol)
    print_lesson_table("By Entry Timing", by_entry)
    print_lesson_table("By Exit Timing", by_exit)
    print_lesson_table("By Learning Label", by_learning)
    print_lesson_table("By Symbol + Entry Timing", by_symbol_entry[:40])

    if args.details:
        print_details(where_sql, params)

    print()
    print("Notes")
    print("-----")
    print("  Recommendations are deterministic summaries, not live trading rules.")
    print("  Require more samples before enabling any timing-based live modifier.")
    print("  This report is designed to surface entry/exit timing candidates for review.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
