#!/usr/bin/env python3
"""
Trend context report — read-only.

Joins historical_trend_context to historical_signal_outcomes and
historical_trade_outcomes to show which trend regimes helped or hurt.

Usage:
  python3 trend_context_report.py --start-date 2026-05-18 --end-date 2026-05-22
  python3 trend_context_report.py --symbol AAPL
  python3 trend_context_report.py --date 2026-05-22
"""

import argparse
from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository

repo = OpsCheckRepository(Path(__file__).resolve().parent / "trades.db")


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


def build_where(args, prefix="t"):
    where = ["1=1"]
    params = []

    if args.date:
        where.append(f"{prefix}.market_date = ?")
        params.append(args.date)
    else:
        if args.start_date:
            where.append(f"{prefix}.market_date >= ?")
            params.append(args.start_date)
        if args.end_date:
            where.append(f"{prefix}.market_date <= ?")
            params.append(args.end_date)

    if args.symbol:
        where.append(f"{prefix}.symbol = ?")
        params.append(args.symbol.upper())

    return " AND ".join(where), params


def fetch_bucket(group_expr, where_sql, params):
    return repo.trend_context_bucket_rows(group_expr, where_sql, params)


def print_bucket(title, rows):
    print()
    print(f"── {title} " + "─" * max(0, 96 - len(title)))

    if not rows:
        print("  No rows.")
        return

    headers = [
        "Bucket",
        "Ctx",
        "Sig",
        "Match",
        "Win",
        "Loss",
        "AvgP&L",
        "TotP&L",
        "Avg%",
        "1d%",
        "5d%",
        "10d%",
        "RS",
        "Dist20",
    ]
    widths = [28, 5, 6, 7, 5, 5, 9, 9, 8, 7, 7, 7, 6, 8]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for r in rows:
        print(
            fmt.format(
                short(r["bucket"], 28),
                r["context_rows"],
                r["signal_rows"],
                r["matched_signals"],
                r["winners"] or 0,
                r["losers"] or 0,
                money(r["avg_signal_pnl"]),
                money(r["total_signal_pnl"]),
                pct(r["avg_signal_pnl_pct"]),
                pct(r["avg_1d"]),
                pct(r["avg_5d"]),
                pct(r["avg_10d"]),
                num(r["avg_rs"], 0),
                pct(r["avg_dist20"]),
            )
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--symbol")
    args = parser.parse_args()

    where_sql, params = build_where(args, "t")

    summary = repo.trend_context_summary_row(where_sql, params)

    by_label = fetch_bucket("t.trend_label", where_sql, params)
    by_regime = fetch_bucket("t.trend_regime", where_sql, params)
    by_confidence = fetch_bucket("t.trend_confidence", where_sql, params)
    by_benchmark = fetch_bucket("t.benchmark_symbol", where_sql, params)
    by_symbol_label = fetch_bucket("t.symbol || ':' || t.trend_label", where_sql, params)

    print("=" * 132)
    print("  Trend Context Report")
    print("=" * 132)

    if args.date:
        print(f"  date       : {args.date}")
    if args.start_date or args.end_date:
        print(f"  date range : {args.start_date or '-'} to {args.end_date or '-'}")
    if args.symbol:
        print(f"  symbol     : {args.symbol.upper()}")

    print()
    print("Summary")
    print("-------")
    print(f"  Context rows : {summary['context_rows'] or 0}")
    print(f"  Dates        : {summary['dates'] or 0}")
    print(f"  Symbols      : {summary['symbols'] or 0}")

    print_bucket("By Trend Label", by_label)
    print_bucket("By Trend Regime", by_regime)
    print_bucket("By Trend Confidence", by_confidence)
    print_bucket("By Benchmark", by_benchmark)
    print_bucket("By Symbol + Trend Label", by_symbol_label[:50])

    print()
    print("Notes")
    print("-----")
    print("  Trend context is learning-only and does not modify live trading.")
    print("  Signal P&L is from historical_signal_outcomes joined by date+symbol.")
    print("  Use this to identify trend regimes that help or hurt signal outcomes.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
