#!/usr/bin/env python3
"""
Excursion Report

Read-only MFE/MAE analysis for closed matched trades.

For each matched trade:
- Fetches 1-minute Alpaca IEX bars between entry and exit
- Calculates max favorable excursion (MFE)
- Calculates max adverse excursion (MAE)
- Calculates profit giveback from best available unrealized profit
- Helps determine whether losses are entry problems or exit problems

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
from services.excursion_service import (
    build_default_excursion_service,
    classify_trade,
    parse_ts,
    pct_change,
)


ET = pytz.timezone("America/New_York")
BASE_DIR = Path(__file__).resolve().parent
EXCURSION_MEMORY_FILE = BASE_DIR / "excursion_memory.json"


def fetch_trade_bars(symbol, entry_ts_utc, exit_ts_utc):
    return build_default_excursion_service().fetch_trade_bars(
        symbol,
        entry_ts_utc,
        exit_ts_utc,
    )


def analyze_trade(row):
    return build_default_excursion_service().analyze_trade(row)


def load_matched_trades(target_date=None, symbol=None, limit=100):
    return build_default_excursion_service().load_matched_trades(
        target_date,
        symbol,
        limit,
    )


def avg(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else 0.0


def summarize(results):
    valid = [r for r in results if r and not r.get("error")]
    errors = [r for r in results if r and r.get("error")]

    by_class = defaultdict(list)
    by_symbol = defaultdict(list)
    by_setup = defaultdict(list)

    for r in valid:
        by_class[r["excursion_classification"]].append(r)
        by_symbol[r["symbol"]].append(r)
        by_setup[r.get("setup_label") or "unknown"].append(r)

    print()
    print("── Summary ───────────────────────────────────────────")
    print(f"Analyzed trades   : {len(results)}")
    print(f"Trades with bars  : {len(valid)}")
    print(f"Rows with errors  : {len(errors)}")

    if valid:
        print(f"Total realized P&L: ${sum(r['realized_pnl'] for r in valid):+.2f}")
        print(f"Avg MFE %         : {avg([r.get('mfe_pct') for r in valid]):+.3f}%")
        print(f"Avg MAE %         : {avg([r.get('mae_pct') for r in valid]):+.3f}%")
        print(f"Avg giveback %    : {avg([r.get('profit_giveback_pct') for r in valid]):+.1f}%")

    print()
    print("── Classification ────────────────────────────────────")
    if not by_class:
        print("  No valid classifications.")
    else:
        for cls, rows in sorted(by_class.items(), key=lambda x: -len(x[1])):
            pnl = sum(r["realized_pnl"] for r in rows)
            print(
                f"  {cls:<28} {len(rows):>4} "
                f"P&L=${pnl:+.2f} "
                f"AvgMFE={avg([r.get('mfe_pct') for r in rows]):+.3f}% "
                f"AvgMAE={avg([r.get('mae_pct') for r in rows]):+.3f}% "
                f"AvgGiveback={avg([r.get('profit_giveback_pct') for r in rows]):+.1f}%"
            )

    print()
    print("── By symbol ─────────────────────────────────────────")
    if not by_symbol:
        print("  No valid symbols.")
    else:
        print(f"  {'Symbol':<8} {'N':>4} {'P&L':>10} {'AvgMFE%':>9} {'AvgMAE%':>9} {'Giveback%':>10}")
        print(f"  {'-'*8} {'-'*4} {'-'*10} {'-'*9} {'-'*9} {'-'*10}")

        for sym, rows in sorted(by_symbol.items(), key=lambda x: sum(r["realized_pnl"] for r in x[1])):
            pnl = sum(r["realized_pnl"] for r in rows)
            print(
                f"  {sym:<8} {len(rows):>4} "
                f"${pnl:>+9.2f} "
                f"{avg([r.get('mfe_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('mae_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('profit_giveback_pct') for r in rows]):>10.1f}"
            )

    print()
    print("── By setup label ────────────────────────────────────")
    if not by_setup:
        print("  No setup labels.")
    else:
        print(f"  {'Setup':<28} {'N':>4} {'P&L':>10} {'AvgMFE%':>9} {'AvgMAE%':>9} {'Giveback%':>10}")
        print(f"  {'-'*28} {'-'*4} {'-'*10} {'-'*9} {'-'*9} {'-'*10}")

        for setup, rows in sorted(by_setup.items(), key=lambda x: sum(r["realized_pnl"] for r in x[1])):
            pnl = sum(r["realized_pnl"] for r in rows)
            print(
                f"  {setup:<28} {len(rows):>4} "
                f"${pnl:>+9.2f} "
                f"{avg([r.get('mfe_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('mae_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('profit_giveback_pct') for r in rows]):>10.1f}"
            )


def print_trade_samples(results, limit=20):
    valid = [r for r in results if r and not r.get("error")]

    print()
    print("── Worst givebacks / trade management issues ─────────")
    givebacks = [
        r for r in valid
        if r.get("profit_giveback_pct") is not None
    ]
    givebacks = sorted(givebacks, key=lambda r: r.get("profit_giveback_pct") or 0, reverse=True)

    if not givebacks:
        print("  None.")
    else:
        print(
            f"  {'Exit time':<19} {'Sym':<6} {'P&L':>9} "
            f"{'MFE$':>9} {'MAE$':>9} {'Giveback%':>10} {'Class':<24} Setup"
        )
        for r in givebacks[:limit]:
            print(
                f"  {r['exit_timestamp']:<19} {r['symbol']:<6} "
                f"${r['realized_pnl']:>+8.2f} "
                f"${r['mfe_dollars']:>+8.2f} "
                f"${r['mae_dollars']:>+8.2f} "
                f"{str(r.get('profit_giveback_pct')):>10} "
                f"{r.get('excursion_classification'):<24} "
                f"{r.get('setup_label') or '-'}"
            )

    print()
    print("── Bad entries / never worked ────────────────────────")
    bad_entries = [
        r for r in valid
        if r.get("excursion_classification") in ("bad_entry_never_worked", "large_adverse_excursion")
    ]
    bad_entries = sorted(bad_entries, key=lambda r: r.get("mae_pct") or 0)

    if not bad_entries:
        print("  None.")
    else:
        print(
            f"  {'Exit time':<19} {'Sym':<6} {'P&L':>9} "
            f"{'MFE%':>8} {'MAE%':>8} {'Class':<24} Setup"
        )
        for r in bad_entries[:limit]:
            print(
                f"  {r['exit_timestamp']:<19} {r['symbol']:<6} "
                f"${r['realized_pnl']:>+8.2f} "
                f"{r.get('mfe_pct'):>8} "
                f"{r.get('mae_pct'):>8} "
                f"{r.get('excursion_classification'):<24} "
                f"{r.get('setup_label') or '-'}"
            )



def build_excursion_memory(results, target_date=None):
    valid = [r for r in results if r and not r.get("error")]

    by_symbol = defaultdict(list)
    by_setup = defaultdict(list)
    by_class = defaultdict(list)

    for r in valid:
        by_symbol[r["symbol"]].append(r)
        by_setup[r.get("setup_label") or "unknown"].append(r)
        by_class[r.get("excursion_classification") or "unknown"].append(r)

    def bucket(rows):
        n = len(rows)
        total_pnl = sum(float(r.get("realized_pnl") or 0) for r in rows)
        avg_mfe = avg([r.get("mfe_pct") for r in rows])
        avg_mae = avg([r.get("mae_pct") for r in rows])
        avg_giveback = avg([r.get("profit_giveback_pct") for r in rows])

        bad_entries = sum(1 for r in rows if r.get("excursion_classification") == "bad_entry_never_worked")
        winner_losers = sum(1 for r in rows if r.get("excursion_classification") == "winner_became_loser")
        givebacks = sum(1 for r in rows if r.get("excursion_classification") == "profit_giveback")

        if n < 2:
            recommendation = "observe"
            reason = f"sample too small: {n} closed trades"
        elif bad_entries / n >= 0.5:
            recommendation = "tighten_entries"
            reason = f"bad_entry_rate={bad_entries / n * 100:.1f}%"
        elif (winner_losers + givebacks) / n >= 0.5:
            recommendation = "improve_exits"
            reason = f"giveback_or_winner_loser_rate={(winner_losers + givebacks) / n * 100:.1f}%"
        elif total_pnl > 0 and avg_giveback < 40:
            recommendation = "working"
            reason = f"positive pnl ${total_pnl:.2f} with avg_giveback={avg_giveback:.1f}%"
        else:
            recommendation = "neutral"
            reason = f"mixed excursion profile, pnl=${total_pnl:.2f}"

        return {
            "trades": n,
            "total_pnl": round(total_pnl, 2),
            "avg_mfe_pct": round(avg_mfe, 3),
            "avg_mae_pct": round(avg_mae, 3),
            "avg_profit_giveback_pct": round(avg_giveback, 1),
            "bad_entry_count": bad_entries,
            "winner_became_loser_count": winner_losers,
            "profit_giveback_count": givebacks,
            "recommendation": recommendation,
            "reason": reason,
        }

    return {
        "generated_at": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
        "date": target_date,
        "trades_analyzed": len(results),
        "trades_with_bar_data": len(valid),
        "symbol_memory": {
            k: bucket(v)
            for k, v in sorted(by_symbol.items())
        },
        "setup_memory": {
            k: bucket(v)
            for k, v in sorted(by_setup.items())
        },
        "classification_memory": {
            k: bucket(v)
            for k, v in sorted(by_class.items())
        },
    }


def write_excursion_memory(results, target_date=None):
    memory = build_excursion_memory(results, target_date)
    atomic_write_json(EXCURSION_MEMORY_FILE, memory)
    print(f"Wrote {EXCURSION_MEMORY_FILE}")
    return memory

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Exit date YYYY-MM-DD. Default: all recent matched trades.")
    parser.add_argument("--symbol")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--write-memory", action="store_true", help="Write excursion_memory.json")
    args = parser.parse_args()

    print("=" * 72)
    title_date = args.date or "recent"
    print(f"  Excursion Report — {title_date}")
    print("=" * 72)

    rows, results = build_default_excursion_service().analyze_trades(
        target_date=args.date,
        symbol=args.symbol,
        limit=args.limit,
    )

    print(f"Matched trades loaded: {len(rows)}")

    summarize(results)
    print_trade_samples(results, limit=args.samples)

    if args.write_memory:
        write_excursion_memory(results, args.date)

    errors = [r for r in results if r and r.get("error")]
    if errors:
        print()
        print("── Errors / skipped rows ─────────────────────────────")
        for r in errors[:10]:
            print(f"  id={r.get('id')} {r.get('symbol')}: {r.get('error')}")


if __name__ == "__main__":
    main()
