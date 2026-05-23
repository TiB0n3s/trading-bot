#!/usr/bin/env python3
"""
Signal timing report — read-only.

Summarizes historical_signal_outcomes to show early/late entry and exit patterns.

Usage:
  python3 signal_timing_report.py
  python3 signal_timing_report.py --date 2026-05-22
  python3 signal_timing_report.py --symbol AAPL
"""

import argparse
from datetime import date

from db import DB_PATH, get_connection


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


def short(v, width):
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def print_bucket(title, rows):
    print()
    print(f"── {title} " + "─" * max(0, 88 - len(title)))

    if not rows:
        print("  No rows.")
        return

    print(f"  {'Bucket':<28} {'N':>6} {'Matched':>8} {'AvgDelay':>9} {'AvgP&L':>10} {'TotalP&L':>10} {'AvgP&L%':>9}")
    print(f"  {'-'*28} {'-'*6} {'-'*8} {'-'*9} {'-'*10} {'-'*10} {'-'*9}")

    for r in rows:
        print(
            f"  {short(r['bucket'], 28):<28} "
            f"{r['n']:>6} "
            f"{r['matched']:>8} "
            f"{('-' if r['avg_delay'] is None else f'{float(r['avg_delay']):.1f}'):>9} "
            f"{money(r['avg_pnl']):>10} "
            f"{money(r['total_pnl']):>10} "
            f"{pct(r['avg_pnl_pct']):>9}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--symbol")
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

    where_sql = " AND ".join(where)

    with get_connection(DB_PATH) as con:
        summary = con.execute(
            f"""
            SELECT
              COUNT(*) AS signals,
              SUM(CASE WHEN matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
              SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS winners,
              SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) AS losers,
              ROUND(SUM(realized_pnl), 2) AS total_pnl,
              ROUND(AVG(realized_pnl), 2) AS avg_pnl
            FROM historical_signal_outcomes
            WHERE {where_sql}
            """,
            params,
        ).fetchone()

        by_learning = con.execute(
            f"""
            SELECT
              learning_label AS bucket,
              COUNT(*) AS n,
              SUM(CASE WHEN matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
              ROUND(AVG(entry_delay_minutes), 1) AS avg_delay,
              ROUND(AVG(realized_pnl), 2) AS avg_pnl,
              ROUND(SUM(realized_pnl), 2) AS total_pnl,
              ROUND(AVG(realized_pnl_pct), 2) AS avg_pnl_pct
            FROM historical_signal_outcomes
            WHERE {where_sql}
            GROUP BY learning_label
            ORDER BY total_pnl DESC
            """,
            params,
        ).fetchall()

        by_entry = con.execute(
            f"""
            SELECT
              entry_timing_label AS bucket,
              COUNT(*) AS n,
              SUM(CASE WHEN matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
              ROUND(AVG(entry_delay_minutes), 1) AS avg_delay,
              ROUND(AVG(realized_pnl), 2) AS avg_pnl,
              ROUND(SUM(realized_pnl), 2) AS total_pnl,
              ROUND(AVG(realized_pnl_pct), 2) AS avg_pnl_pct
            FROM historical_signal_outcomes
            WHERE {where_sql}
            GROUP BY entry_timing_label
            ORDER BY total_pnl DESC
            """,
            params,
        ).fetchall()

        by_symbol = con.execute(
            f"""
            SELECT
              symbol AS bucket,
              COUNT(*) AS n,
              SUM(CASE WHEN matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
              ROUND(AVG(entry_delay_minutes), 1) AS avg_delay,
              ROUND(AVG(realized_pnl), 2) AS avg_pnl,
              ROUND(SUM(realized_pnl), 2) AS total_pnl,
              ROUND(AVG(realized_pnl_pct), 2) AS avg_pnl_pct
            FROM historical_signal_outcomes
            WHERE {where_sql}
            GROUP BY symbol
            ORDER BY total_pnl DESC
            LIMIT 30
            """,
            params,
        ).fetchall()

        details = []
        if args.details:
            details = con.execute(
                f"""
                SELECT *
                FROM historical_signal_outcomes
                WHERE {where_sql}
                ORDER BY market_date, symbol, signal_timestamp
                LIMIT 100
                """,
                params,
            ).fetchall()

    print("=" * 120)
    print("  Signal Timing Report")
    print("=" * 120)
    if args.date:
        print(f"  date   : {args.date}")
    if args.symbol:
        print(f"  symbol : {args.symbol.upper()}")

    print()
    print("Summary")
    print("-------")
    print(f"  Signals   : {summary['signals'] or 0}")
    print(f"  Matched   : {summary['matched'] or 0}")
    print(f"  Winners   : {summary['winners'] or 0}")
    print(f"  Losers    : {summary['losers'] or 0}")
    print(f"  Total P&L : {money(summary['total_pnl'])}")
    print(f"  Avg P&L   : {money(summary['avg_pnl'])}")

    print_bucket("By Learning Label", by_learning)
    print_bucket("By Entry Timing", by_entry)
    print_bucket("By Symbol", by_symbol)

    if details:
        print()
        print("── Details ─────────────────────────────────────────")
        print(f"  {'Date':<10} {'Sym':<6} {'Act':<5} {'EntryDelay':>10} {'ExitDelay':>9} {'P&L':>9} {'Learning':<26} Reason")
        print(f"  {'-'*10} {'-'*6} {'-'*5} {'-'*10} {'-'*9} {'-'*9} {'-'*26} {'-'*50}")
        for r in details:
            ed = "-" if r["entry_delay_minutes"] is None else f"{float(r['entry_delay_minutes']):.1f}"
            xd = "-" if r["exit_delay_minutes"] is None else f"{float(r['exit_delay_minutes']):.1f}"
            print(
                f"  {short(r['market_date'], 10):<10} "
                f"{short(r['symbol'], 6):<6} "
                f"{short(r['action'], 5):<5} "
                f"{ed:>10} "
                f"{xd:>9} "
                f"{money(r['realized_pnl']):>9} "
                f"{short(r['learning_label'], 26):<26} "
                f"{short(r['learning_reason'], 80)}"
            )

    print()
    print("Notes")
    print("-----")
    print("  This report links historical signal logs to reconstructed Alpaca outcomes.")
    print("  It is learning-only and does not modify live trading behavior.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
