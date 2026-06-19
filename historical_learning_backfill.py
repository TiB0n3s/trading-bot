#!/usr/bin/env python3
"""
Historical learning backfill wrapper.

Runs the learning-only rebuild/reporting steps in the correct order.

This does NOT modify live trades or matched_trades.

Pipeline:
  1. Build deduped signal events
  2. Build signal outcomes
  3. Build trend context
  4. Generate predictions per date
  5. Run validation reports

Usage:
  python3 historical_learning_backfill.py --start-date 2026-05-18 --end-date 2026-05-22
  python3 historical_learning_backfill.py --start-date 2026-05-18 --end-date 2026-05-22 --skip-reports
  python3 historical_learning_backfill.py --start-date 2026-05-18 --end-date 2026-05-22 --symbol AAPL
"""

import argparse
import subprocess
import sys
from datetime import date, timedelta


def date_range(start_date, end_date):
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d.isoformat()
        d += timedelta(days=1)


def run(label, cmd, allow_fail=False):
    print()
    print("─" * 96)
    print(f"{label}")
    print("─" * 96)
    print(" ".join(cmd))

    proc = subprocess.run(cmd, text=True)

    if proc.returncode == 0:
        print(f"[OK] {label}")
        return True

    msg = f"[FAIL] {label} exited {proc.returncode}"
    if allow_fail:
        print(msg)
        return False

    raise SystemExit(msg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbol", help="Optional symbol filter for signal rebuild/prediction reports")
    parser.add_argument("--skip-context", action="store_true", help="Skip pre_market_research_data context backfill")
    parser.add_argument("--skip-trends", action="store_true", help="Skip trend_context_builder")
    parser.add_argument("--skip-predictions", action="store_true", help="Skip predict_symbol_outcomes")
    parser.add_argument("--skip-reports", action="store_true", help="Skip final reports")
    parser.add_argument("--no-replace", action="store_true", help="Do not replace signal event/outcome tables")
    args = parser.parse_args()

    dates = list(date_range(args.start_date, args.end_date))
    if not dates:
        raise SystemExit("No weekday dates in requested range")

    py = sys.executable

    print("=" * 96)
    print(" Historical Learning Backfill")
    print("=" * 96)
    print(f"  Date range : {args.start_date} to {args.end_date}")
    print(f"  Dates      : {', '.join(dates)}")
    print(f"  Symbol     : {args.symbol.upper() if args.symbol else '(all)'}")
    print(f"  Replace    : {not args.no_replace}")

    symbol_args = []
    if args.symbol:
        symbol_args = ["--symbol", args.symbol.upper()]

    replace_args = [] if args.no_replace else ["--replace"]

    if not args.skip_context:
        for d in dates:
            run(
                f"Backfill daily symbol context — {d}",
                [
                    py,
                    "pre_market_research_data.py",
                    "--date",
                    d,
                    "--raw-output",
                    f"/tmp/raw_market_research_{d}.backfill.json",
                    "--build-output",
                    f"/tmp/market_context_{d}.backfill.json",
                    "--ingest-context",
                ],
                allow_fail=False,
            )

    run(
        "Build deduped historical signal events",
        [
            py,
            "signal_event_builder.py",
            "--start-date",
            args.start_date,
            "--end-date",
            args.end_date,
            *symbol_args,
            *replace_args,
        ],
    )

    run(
        "Build historical signal outcomes",
        [
            py,
            "signal_outcome_builder.py",
            "--start-date",
            args.start_date,
            "--end-date",
            args.end_date,
            *symbol_args,
            *replace_args,
        ],
    )

    if not args.skip_trends:
        trend_cmd = [
            py,
            "trend_context_builder.py",
            "--start-date",
            args.start_date,
            "--end-date",
            args.end_date,
        ]
        if args.symbol:
            trend_cmd += ["--symbol", args.symbol.upper()]
        run("Build historical trend context", trend_cmd)

    if not args.skip_predictions:
        for d in dates:
            pred_cmd = [py, "predict_symbol_outcomes.py", "--date", d]
            if args.symbol:
                pred_cmd += ["--symbol", args.symbol.upper()]
            run(f"Generate observe-only predictions — {d}", pred_cmd)

    if not args.skip_reports:
        for d in dates:
            report_symbol_args = ["--symbol", args.symbol.upper()] if args.symbol else []

            run(
                f"Prediction report — {d}",
                [py, "intelligence_prediction_report.py", "--date", d, *report_symbol_args],
                allow_fail=True,
            )

            run(
                f"Signal timing lesson report — {d}",
                [py, "signal_timing_lesson_report.py", "--date", d, *report_symbol_args],
                allow_fail=True,
            )

            run(
                f"Trend context report — {d}",
                [py, "trend_context_report.py", "--date", d, *report_symbol_args],
                allow_fail=True,
            )

    print()
    print("=" * 96)
    print("[OK] Historical learning backfill complete")
    print("=" * 96)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
