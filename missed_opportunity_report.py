#!/usr/bin/env python3
"""
Missed Opportunity Report

Read-only analysis of rejected BUY signals.

For each rejected BUY signal, this script:
- Reads the rejected signal from trades.db
- Fetches forward 1-minute Alpaca IEX bars
- Calculates 15m / 30m / 60m forward return
- Calculates max favorable excursion and max adverse excursion
- Groups results by rejection category and symbol

This does not place, cancel, or modify orders.
"""

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytz

from policy_artifacts import atomic_write_json
from services.missed_opportunity_service import (
    bar_at_or_after,
    build_default_missed_opportunity_service,
    category,
    parse_ts,
    pct_change,
)


ET = pytz.timezone("America/New_York")
BASE_DIR = Path(__file__).resolve().parent
MISSED_MEMORY_FILE = BASE_DIR / "missed_opportunity_memory.json"


def fetch_forward_bars(symbol, ts_utc, minutes=75):
    return build_default_missed_opportunity_service().fetch_forward_bars(
        symbol,
        ts_utc,
        minutes=minutes,
    )


def analyze_row(row):
    return build_default_missed_opportunity_service().analyze_row(row)


def load_rejections(target_date, symbol=None, category_filter=None, limit=80):
    return build_default_missed_opportunity_service().load_rejections(
        target_date,
        symbol=symbol,
        category_filter=category_filter,
        limit=limit,
    )


def avg(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else 0.0


def summarize(results):
    valid = [r for r in results if r and not r.get("error")]
    errors = [r for r in results if r and r.get("error")]

    by_category = defaultdict(list)
    by_symbol = defaultdict(list)
    by_class = defaultdict(int)

    for r in valid:
        by_category[r["category"]].append(r)
        by_symbol[r["symbol"]].append(r)
        by_class[r["missed_classification"]] += 1

    print()
    print("── Summary ───────────────────────────────────────────")
    print(f"Analyzed rows      : {len(results)}")
    print(f"Rows with bar data : {len(valid)}")
    print(f"Rows with errors   : {len(errors)}")

    print()
    print("Classification:")
    if by_class:
        for k, n in sorted(by_class.items(), key=lambda x: -x[1]):
            print(f"  {k:<22} {n}")
    else:
        print("  none")

    print()
    print("── By rejection category ─────────────────────────────")
    if not by_category:
        print("  No valid rows.")
    else:
        print(f"  {'Category':<28} {'N':>4} {'Avg30m%':>9} {'AvgMFE%':>9} {'AvgMAE%':>9} {'MissedGood':>10}")
        print(f"  {'-'*28} {'-'*4} {'-'*9} {'-'*9} {'-'*9} {'-'*10}")

        for cat, rows in sorted(by_category.items(), key=lambda x: -len(x[1])):
            missed = sum(1 for r in rows if r.get("missed_classification") == "missed_good_trade")
            print(
                f"  {cat:<28} {len(rows):>4} "
                f"{avg([r.get('return_30m_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('mfe_75m_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('mae_75m_pct') for r in rows]):>9.3f} "
                f"{missed:>10}"
            )

    print()
    print("── By symbol ─────────────────────────────────────────")
    if not by_symbol:
        print("  No valid rows.")
    else:
        print(f"  {'Symbol':<8} {'N':>4} {'Avg30m%':>9} {'AvgMFE%':>9} {'AvgMAE%':>9} {'MissedGood':>10}")
        print(f"  {'-'*8} {'-'*4} {'-'*9} {'-'*9} {'-'*9} {'-'*10}")

        for sym, rows in sorted(by_symbol.items(), key=lambda x: -len(x[1]))[:25]:
            missed = sum(1 for r in rows if r.get("missed_classification") == "missed_good_trade")
            print(
                f"  {sym:<8} {len(rows):>4} "
                f"{avg([r.get('return_30m_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('mfe_75m_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('mae_75m_pct') for r in rows]):>9.3f} "
                f"{missed:>10}"
            )


def print_samples(results, limit=20):
    valid = [r for r in results if r and not r.get("error")]
    valid = sorted(valid, key=lambda r: (r.get("mfe_75m_pct") or 0), reverse=True)

    print()
    print("── Top possible missed good trades ───────────────────")
    if not valid:
        print("  None.")
        return

    print(
        f"  {'Time':<19} {'Sym':<6} {'Cat':<22} "
        f"{'30m%':>7} {'60m%':>7} {'MFE%':>7} {'MAE%':>7} "
        f"{'Class':<18} Reason"
    )

    for r in valid[:limit]:
        print(
            f"  {r['timestamp']:<19} {r['symbol']:<6} {r['category']:<22} "
            f"{str(r.get('return_30m_pct')):>7} "
            f"{str(r.get('return_60m_pct')):>7} "
            f"{str(r.get('mfe_75m_pct')):>7} "
            f"{str(r.get('mae_75m_pct')):>7} "
            f"{r.get('missed_classification'):<18} "
            f"{(r.get('reason') or '')[:80]}"
        )



def build_missed_opportunity_memory(results, target_date):
    valid = [r for r in results if r and not r.get("error")]

    by_category = defaultdict(list)
    by_symbol = defaultdict(list)

    for r in valid:
        by_category[r["category"]].append(r)
        by_symbol[r["symbol"]].append(r)

    def bucket(rows):
        n = len(rows)
        missed_good = sum(1 for r in rows if r.get("missed_classification") == "missed_good_trade")
        good_reject = sum(1 for r in rows if r.get("missed_classification") == "good_rejection")
        avg_30m = avg([r.get("return_30m_pct") for r in rows])
        avg_mfe = avg([r.get("mfe_75m_pct") for r in rows])
        avg_mae = avg([r.get("mae_75m_pct") for r in rows])

        missed_good_rate = (missed_good / n * 100.0) if n else 0.0
        good_reject_rate = (good_reject / n * 100.0) if n else 0.0

        if n < 3:
            recommendation = "observe"
            reason = f"sample too small: {n} rejected signals"
        elif missed_good_rate >= 35 and avg_30m > 0.20:
            recommendation = "review_too_strict"
            reason = f"missed_good_rate={missed_good_rate:.1f}% and avg_30m={avg_30m:.3f}%"
        elif good_reject_rate >= 50 and avg_30m <= 0:
            recommendation = "keep_strict"
            reason = f"good_reject_rate={good_reject_rate:.1f}% and avg_30m={avg_30m:.3f}%"
        else:
            recommendation = "neutral"
            reason = f"mixed: missed_good_rate={missed_good_rate:.1f}%, good_reject_rate={good_reject_rate:.1f}%"

        return {
            "signals": n,
            "missed_good": missed_good,
            "good_rejection": good_reject,
            "missed_good_rate_pct": round(missed_good_rate, 1),
            "good_reject_rate_pct": round(good_reject_rate, 1),
            "avg_30m_return_pct": round(avg_30m, 3),
            "avg_mfe_75m_pct": round(avg_mfe, 3),
            "avg_mae_75m_pct": round(avg_mae, 3),
            "recommendation": recommendation,
            "reason": reason,
        }

    memory = {
        "generated_at": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
        "date": target_date,
        "signals_analyzed": len(results),
        "signals_with_bar_data": len(valid),
        "category_memory": {
            k: bucket(v)
            for k, v in sorted(by_category.items())
        },
        "symbol_memory": {
            k: bucket(v)
            for k, v in sorted(by_symbol.items())
        },
    }

    return memory


def write_missed_opportunity_memory(results, target_date):
    memory = build_missed_opportunity_memory(results, target_date)
    atomic_write_json(MISSED_MEMORY_FILE, memory)
    print(f"Wrote {MISSED_MEMORY_FILE}")
    return memory

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(ET).date().isoformat())
    parser.add_argument("--symbol")
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--write-memory", action="store_true", help="Write missed_opportunity_memory.json")
    args = parser.parse_args()

    print("=" * 72)
    print(f"  Missed Opportunity Report — {args.date}")
    print("=" * 72)

    rows, results = build_default_missed_opportunity_service().analyze_rejections(
        target_date=args.date,
        symbol=args.symbol,
        category_filter=args.category,
        limit=args.limit,
    )

    print(f"Rejected BUY rows loaded: {len(rows)}")

    summarize(results)
    print_samples(results, limit=args.samples)

    if args.write_memory:
        write_missed_opportunity_memory(results, args.date)

    errors = [r for r in results if r and r.get("error")]
    if errors:
        print()
        print("── Errors / skipped rows ─────────────────────────────")
        for r in errors[:10]:
            print(f"  id={r.get('id')} {r.get('symbol')} {r.get('category')}: {r.get('error')}")


if __name__ == "__main__":
    main()
