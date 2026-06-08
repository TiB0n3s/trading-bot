#!/usr/bin/env python3
"""
Blocked signal outcome report — read-only DB analysis.

First pass: DB-only attribution for rejected BUY signals.
Shows which gates blocked buys and what live context existed at the time.

Usage:
  python3 blocked_signal_outcome_report.py
  python3 blocked_signal_outcome_report.py --week
  python3 blocked_signal_outcome_report.py --all
  python3 blocked_signal_outcome_report.py --date 2026-05-13
  python3 blocked_signal_outcome_report.py --category prediction_gate
  python3 blocked_signal_outcome_report.py --symbol NVDA
"""

import argparse
from collections import Counter, defaultdict

from services.blocked_signal_outcome_service import (
    build_default_blocked_signal_outcome_service,
)


def category(reason):
    if not reason:
        return "unknown"
    if ":" in reason:
        return reason.split(":", 1)[0].strip()
    return "claude_rejection"


def short(value, width=70):
    if value is None:
        return "-"
    s = str(value)
    return s if len(s) <= width else s[: width - 1] + "…"


def avg(values):
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def print_section(title):
    print()
    print("── " + title + " " + "─" * max(0, 72 - len(title)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Date YYYY-MM-DD, default=today")
    parser.add_argument("--week", action="store_true", help="Current week Monday-Friday")
    parser.add_argument("--all", action="store_true", help="All history")
    parser.add_argument("--symbol", help="Filter to one symbol")
    parser.add_argument("--category", help="Filter to one rejection category")
    parser.add_argument("--limit", type=int, default=20, help="Recent samples to show")
    args = parser.parse_args()

    try:
        payload = build_default_blocked_signal_outcome_service().payload(
            target_date=args.date,
            week=args.week,
            all_history=args.all,
            symbol=args.symbol,
            category=args.category,
            category_fn=category,
        )
    except FileNotFoundError as e:
        raise SystemExit(f"ERROR: {e.filename} not found")

    rows = payload.rows

    print()
    print("=" * 80)
    print("  Blocked Signal Outcome Report — DB Context")
    print("=" * 80)
    print(f"  Blocked BUY rows : {len(rows)}")
    if payload.symbol:
        print(f"  Symbol filter    : {payload.symbol}")
    if payload.category:
        print(f"  Category filter  : {payload.category}")

    if not rows:
        print()
        print("No blocked BUY rows matched this range/filter.")
        return

    by_cat = defaultdict(list)
    by_symbol = defaultdict(list)

    for r in rows:
        cat = category(r["rejection_reason"])
        by_cat[cat].append(r)
        by_symbol[r["symbol"]].append(r)

    print_section("By rejection category")
    print(f"  {'Category':<28} {'Count':>6} {'AvgPred':>8}  Top symbols")
    print(f"  {'-' * 28} {'-' * 6} {'-' * 8}  {'-' * 34}")
    for cat, group in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        avg_pred = avg([r["prediction_score"] for r in group])
        top_symbols = Counter(r["symbol"] for r in group).most_common(6)
        top_symbols_str = ", ".join(f"{sym}:{n}" for sym, n in top_symbols)
        avg_pred_str = f"{avg_pred:.2f}" if avg_pred is not None else "-"
        print(f"  {cat:<28} {len(group):>6} {avg_pred_str:>8}  {top_symbols_str}")

    print_section("By symbol")
    print(f"  {'Symbol':<8} {'Count':>6} {'AvgPred':>8}  Top categories")
    print(f"  {'-' * 8} {'-' * 6} {'-' * 8}  {'-' * 38}")
    for sym, group in sorted(by_symbol.items(), key=lambda x: -len(x[1]))[:25]:
        avg_pred = avg([r["prediction_score"] for r in group])
        top_cats = Counter(category(r["rejection_reason"]) for r in group).most_common(5)
        top_cats_str = ", ".join(f"{cat}:{n}" for cat, n in top_cats)
        avg_pred_str = f"{avg_pred:.2f}" if avg_pred is not None else "-"
        print(f"  {sym:<8} {len(group):>6} {avg_pred_str:>8}  {top_cats_str}")

    print_section("Top prediction reasons")
    pred_reasons = Counter(
        r["prediction_reason"] or "-" for r in rows if r["prediction_reason"] is not None
    )
    if pred_reasons:
        for reason, n in pred_reasons.most_common(15):
            print(f"  {n:>5}  {short(reason, 95)}")
    else:
        print("  No prediction_reason values found for this range.")

    print_section("Top setup labels")
    setup_labels = Counter(r["setup_label"] or "unknown" for r in rows)
    for label, n in setup_labels.most_common(15):
        print(f"  {n:>5}  {label}")

    print_section("Top setup policy actions")
    setup_actions = Counter(r["setup_policy_action"] or "unknown" for r in rows)
    for action, n in setup_actions.most_common(10):
        print(f"  {n:>5}  {action}")

    print_section("Effective market bias")
    effective_biases = Counter(r["market_bias_effective"] or "unknown" for r in rows)
    for bias, n in effective_biases.most_common(15):
        print(f"  {n:>5}  {bias}")

    print_section("Original market bias")
    original_biases = Counter(r["market_bias"] or "unknown" for r in rows)
    for bias, n in original_biases.most_common(15):
        print(f"  {n:>5}  {bias}")

    print_section("Recent blocked BUY samples")
    print(
        f"  {'ID':>5} {'Time':<19} {'Sym':<6} {'Cat':<24} "
        f"{'Pred':>5} {'Trend':<18} {'Mom':<10} {'Setup':<34}"
    )
    print(f"  {'-' * 5} {'-' * 19} {'-' * 6} {'-' * 24} {'-' * 5} {'-' * 18} {'-' * 10} {'-' * 34}")
    for r in rows[: args.limit]:
        cat = category(r["rejection_reason"])
        pred = r["prediction_score"]
        pred_str = str(pred) if pred is not None else "-"
        trend = f"{r['trend_direction'] or '-'}/{r['trend_strength'] or '-'}"
        mom = f"{r['momentum_direction'] or '-'}"
        if r["momentum_pct"] is not None:
            mom = f"{mom}:{r['momentum_pct']}"
        setup = r["setup_label"] or "-"
        print(
            f"  {r['id']:>5} {r['timestamp']:<19} {r['symbol']:<6} {cat:<24} "
            f"{pred_str:>5} {trend:<18} {mom:<10} {short(setup, 34):<34}"
        )


if __name__ == "__main__":
    main()
