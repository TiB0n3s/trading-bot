#!/usr/bin/env python3
"""
BUY Opportunity Report — observe-only scoring analysis.

Usage:
  python3 buy_opportunity_report.py
  python3 buy_opportunity_report.py 2026-05-22
"""

import sys
from datetime import date
from collections import defaultdict
from db import DB_PATH, get_connection


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

    print("=" * 90)
    print(f"  BUY Opportunity Report — {target_date}")
    print("=" * 90)

    with get_connection(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT timestamp, symbol, approved, rejection_reason,
                   buy_opportunity_score,
                   buy_opportunity_recommendation,
                   buy_opportunity_reason,
                   market_bias, risk_level, entry_quality,
                   trend_direction, trend_strength,
                   setup_label, setup_policy_action,
                   prediction_score, prediction_decision
            FROM trades
            WHERE timestamp LIKE ?
              AND action = 'buy'
            ORDER BY timestamp ASC
            """,
            (f"{target_date}%",),
        ).fetchall()

    if not rows:
        print("No BUY rows found.")
        return

    total = len(rows)
    approved = sum(1 for r in rows if r["approved"])
    scored = [r for r in rows if r["buy_opportunity_score"] is not None]

    print()
    print("── Summary ─────────────────────────────────────────────────────────────")
    print(f"  BUY rows       : {total}")
    print(f"  Approved       : {approved}")
    print(f"  Scored rows    : {len(scored)}")

    buckets = defaultdict(lambda: {"n": 0, "approved": 0})
    for r in scored:
        rec = r["buy_opportunity_recommendation"] or "unknown"
        buckets[rec]["n"] += 1
        buckets[rec]["approved"] += int(r["approved"] or 0)

    print()
    print("── Recommendation buckets ─────────────────────────────────────────────")
    for rec, item in sorted(buckets.items(), key=lambda x: (-x[1]["n"], x[0])):
        n = item["n"]
        a = item["approved"]
        rate = (a / n * 100) if n else 0
        print(f"  {rec:<24} rows={n:<4} approved={a:<4} approval_rate={rate:5.1f}%")

    print()
    print("── Recent scored BUY rows ─────────────────────────────────────────────")
    print(f"  {'Time':<19} {'Sym':<6} {'Appr':<5} {'Score':>5} {'Rec':<22} {'Setup':<28} Reason")
    print(f"  {'-'*19} {'-'*6} {'-'*5} {'-'*5} {'-'*22} {'-'*28} {'-'*60}")

    for r in scored[-25:]:
        reason = r["rejection_reason"] or ""
        if len(reason) > 80:
            reason = reason[:77] + "..."
        setup = r["setup_label"] or "-"
        if len(setup) > 27:
            setup = setup[:24] + "..."
        print(
            f"  {r['timestamp']:<19} {r['symbol']:<6} {str(r['approved']):<5} "
            f"{str(r['buy_opportunity_score']):>5} "
            f"{str(r['buy_opportunity_recommendation'] or '-'):<22} "
            f"{setup:<28} {reason}"
        )


if __name__ == "__main__":
    main()
