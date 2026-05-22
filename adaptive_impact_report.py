#!/usr/bin/env python3
"""
Adaptive impact report — read-only.

Shows how adaptive confirmation and adaptive churn re-entry affected BUY signal
handling for a given day.

Usage:
  python3 adaptive_impact_report.py
  python3 adaptive_impact_report.py 2026-05-22
"""

import sys
from datetime import date
from collections import defaultdict
from db import DB_PATH, get_connection


def section(title):
    print()
    print("── " + title + " " + "─" * max(0, 70 - len(title)))


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

    print("=" * 80)
    print(f"  Adaptive Impact Report — {target_date}")
    print("=" * 80)

    with get_connection(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT
                timestamp,
                symbol,
                action,
                approved,
                rejection_reason,
                market_bias,
                risk_level,
                entry_quality,
                trend_direction,
                trend_strength,
                setup_label,
                setup_policy_action,
                prediction_score,
                prediction_decision
            FROM trades
            WHERE timestamp LIKE ?
              AND action = 'buy'
            ORDER BY timestamp ASC
            """,
            (f"{target_date}%",),
        ).fetchall()

    total = len(rows)
    approved = [r for r in rows if r["approved"]]
    rejected = [r for r in rows if not r["approved"]]

    trend_conf = [
        r for r in rejected
        if (r["rejection_reason"] or "").startswith("trend_confirmation:")
    ]

    adaptive_required_4 = [
        r for r in trend_conf
        if "required=4" in (r["rejection_reason"] or "")
        or "required 4" in (r["rejection_reason"] or "")
    ]

    adaptive_required_2_mentions = [
        r for r in rows
        if "required=2" in (r["rejection_reason"] or "")
        or "required 2" in (r["rejection_reason"] or "")
        or "reduced to 2" in (r["rejection_reason"] or "")
    ]

    churn_price = [
        r for r in rejected
        if (r["rejection_reason"] or "").startswith("churn_price:")
    ]

    adaptive_churn_not_strong = [
        r for r in churn_price
        if "adaptive churn re-entry not strong enough" in (r["rejection_reason"] or "")
    ]

    adaptive_churn_disabled_or_invalid = [
        r for r in churn_price
        if "adaptive churn re-entry disabled" in (r["rejection_reason"] or "")
        or "invalid signal/last-sell price" in (r["rejection_reason"] or "")
    ]

    section("Summary")
    print(f"  BUY signals                 : {total}")
    print(f"  BUY approved                : {len(approved)}")
    print(f"  BUY rejected                : {len(rejected)}")
    print(f"  Trend-confirmation rejects  : {len(trend_conf)}")
    print(f"  Adaptive required=4 rejects : {len(adaptive_required_4)}")
    print(f"  Churn-price rejects         : {len(churn_price)}")
    print(f"  Churn not-strong-enough     : {len(adaptive_churn_not_strong)}")
    print(f"  Churn disabled/invalid      : {len(adaptive_churn_disabled_or_invalid)}")

    section("Trend confirmation rejects by symbol")
    by_symbol = defaultdict(int)
    for r in trend_conf:
        by_symbol[r["symbol"]] += 1

    if by_symbol:
        for sym, n in sorted(by_symbol.items(), key=lambda x: -x[1]):
            print(f"  {sym:<6} {n:>4}")
    else:
        print("  None")

    section("Adaptive required=4 rejects by symbol")
    by_symbol = defaultdict(int)
    for r in adaptive_required_4:
        by_symbol[r["symbol"]] += 1

    if by_symbol:
        for sym, n in sorted(by_symbol.items(), key=lambda x: -x[1]):
            print(f"  {sym:<6} {n:>4}")
    else:
        print("  None")

    section("Churn-price rejects by symbol")
    by_symbol = defaultdict(int)
    for r in churn_price:
        by_symbol[r["symbol"]] += 1

    if by_symbol:
        for sym, n in sorted(by_symbol.items(), key=lambda x: -x[1]):
            print(f"  {sym:<6} {n:>4}")
    else:
        print("  None")

    section("Recent adaptive/churn samples")
    samples = trend_conf[-10:] + churn_price[-10:]
    if not samples:
        print("  No trend-confirmation or churn-price samples.")
    else:
        print(f"  {'Time':<19} {'Sym':<6} {'Appr':<5} {'Trend':<18} {'Setup':<32} Reason")
        print(f"  {'-'*19} {'-'*6} {'-'*5} {'-'*18} {'-'*32} {'-'*60}")
        for r in samples[-20:]:
            reason = (r["rejection_reason"] or "").replace("\n", " ")
            if len(reason) > 90:
                reason = reason[:87] + "..."
            trend = f"{r['trend_direction']}/{r['trend_strength']}"
            setup = str(r["setup_label"] or "-")
            if len(setup) > 31:
                setup = setup[:28] + "..."
            print(
                f"  {r['timestamp']:<19} {r['symbol']:<6} {str(r['approved']):<5} "
                f"{trend:<18} {setup:<32} {reason}"
            )


if __name__ == "__main__":
    main()
