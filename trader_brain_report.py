#!/usr/bin/env python3
"""
Trader Brain Report — observe-only scoring analytics.

Shows how the deterministic trader-brain scorer compares against current bot
approvals/rejections.

Usage:
  python3 trader_brain_report.py
  python3 trader_brain_report.py --date 2026-05-23
  python3 trader_brain_report.py --week
  python3 trader_brain_report.py --all
"""

import argparse
import json
from strategy.setup_classifier import classify_setup
from collections import defaultdict
from datetime import date, timedelta

from db import DB_PATH, get_connection


def date_clause(args):
    if args.all:
        return "", []

    if args.week:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        saturday = monday + timedelta(days=5)
        return "AND timestamp >= ? AND timestamp < ?", [monday.isoformat(), saturday.isoformat()]

    target = args.date or date.today().isoformat()
    return "AND timestamp LIKE ?", [f"{target}%"]


def bucket_score(score):
    if score is None:
        return "missing"
    score = float(score)
    if score >= 80:
        return "80-100 strong"
    if score >= 70:
        return "70-79 qualified"
    if score >= 55:
        return "55-69 watchlist"
    return "0-54 reject"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Date YYYY-MM-DD, default=today")
    parser.add_argument("--week", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    clause, params = date_clause(args)

    with get_connection(DB_PATH) as con:
        rows = con.execute(f"""
            SELECT
                id,
                timestamp,
                symbol,
                action,
                approved,
                rejection_reason,
                trader_brain_score,
                trader_brain_setup_type,
                trader_brain_approved,
                trader_brain_reason,
                trader_brain_positive_factors,
                trader_brain_risk_factors
            FROM trades
            WHERE 1=1
              {clause}
            ORDER BY id ASC
        """, params).fetchall()

    print()
    print("=" * 72)
    print("  Trader Brain Report")
    print("=" * 72)

    total = len(rows)
    scored = [r for r in rows if r["trader_brain_score"] is not None]

    print(f"  Total rows      : {total}")
    print(f"  Scored rows     : {len(scored)}")
    print(f"  Missing scores  : {total - len(scored)}")

    if not scored:
        print()
        print("  No trader-brain scores found for this period yet.")
        print("  Scores will appear only for signals that reach the observe-only scorer.")
        return 0

    agree_approve = 0
    agree_reject = 0
    bot_yes_tb_no = 0
    bot_no_tb_yes = 0

    by_bucket = defaultdict(int)
    by_setup = defaultdict(int)
    by_setup_classification = defaultdict(int)
    by_posture = defaultdict(int)
    by_symbol = defaultdict(lambda: {"rows": 0, "avg_score": 0.0, "approved": 0})

    for r in scored:
        bot_approved = bool(r["approved"])
        tb_approved = bool(r["trader_brain_approved"])

        if bot_approved and tb_approved:
            agree_approve += 1
        elif not bot_approved and not tb_approved:
            agree_reject += 1
        elif bot_approved and not tb_approved:
            bot_yes_tb_no += 1
        elif not bot_approved and tb_approved:
            bot_no_tb_yes += 1

        by_bucket[bucket_score(r["trader_brain_score"])] += 1
        by_setup[r["trader_brain_setup_type"] or "missing"] += 1

        try:
            positive_factors = json.loads(r["trader_brain_positive_factors"] or "[]")
        except Exception:
            positive_factors = []

        try:
            risk_factors = json.loads(r["trader_brain_risk_factors"] or "[]")
        except Exception:
            risk_factors = []

        thesis_like = {
            "score": r["trader_brain_score"],
            "approved_by_scorer": bool(r["trader_brain_approved"]),
            "setup_type": r["trader_brain_setup_type"],
            "market_bias": None,
            "risk_level": None,
            "entry_quality": None,
            "trend_direction": None,
            "trend_strength": None,
            "benchmark_aligned": None,
            "positive_factors": positive_factors,
            "risk_factors": risk_factors,
        }

        setup_class = classify_setup(thesis_like)
        by_setup_classification[setup_class["label"]] += 1
        by_posture[setup_class["posture"]] += 1

        sym = r["symbol"] or "?"
        by_symbol[sym]["rows"] += 1
        by_symbol[sym]["avg_score"] += float(r["trader_brain_score"] or 0)
        if tb_approved:
            by_symbol[sym]["approved"] += 1

    print()
    print("── Agreement Matrix ───────────────────────────────────")
    print(f"  Bot approved / Brain approved : {agree_approve}")
    print(f"  Bot rejected / Brain rejected : {agree_reject}")
    print(f"  Bot approved / Brain rejected : {bot_yes_tb_no}")
    print(f"  Bot rejected / Brain approved : {bot_no_tb_yes}")

    print()
    print("── Score Buckets ──────────────────────────────────────")
    for bucket, n in sorted(by_bucket.items()):
        print(f"  {bucket:<18} {n:>5}")

    print()
    print("── Setup Types ────────────────────────────────────────")
    for setup, n in sorted(by_setup.items(), key=lambda x: -x[1]):
        print(f"  {setup:<24} {n:>5}")

    print()
    print("── Setup Classifications ──────────────────────────────")
    for setup, n in sorted(by_setup_classification.items(), key=lambda x: -x[1]):
        print(f"  {setup:<28} {n:>5}")

    print()
    print("── Setup Postures ─────────────────────────────────────")
    for posture, n in sorted(by_posture.items(), key=lambda x: -x[1]):
        print(f"  {posture:<28} {n:>5}")

    print()
    print("── Symbol Summary ─────────────────────────────────────")
    print(f"  {'Symbol':<8} {'Rows':>5} {'AvgScore':>9} {'BrainApproved':>14}")
    print(f"  {'-'*8} {'-'*5} {'-'*9} {'-'*14}")

    for sym, d in sorted(by_symbol.items()):
        avg = d["avg_score"] / d["rows"] if d["rows"] else 0
        print(f"  {sym:<8} {d['rows']:>5} {avg:>9.1f} {d['approved']:>14}")

    print()
    print("── Recent Disagreements ───────────────────────────────")
    disagreements = [
        r for r in scored
        if bool(r["approved"]) != bool(r["trader_brain_approved"])
    ]

    if not disagreements:
        print("  No disagreements in this period.")
    else:
        print(f"  {'ID':>5} {'Time':<19} {'Sym':<6} {'Act':<5} {'Bot':<5} {'Brain':<6} {'Score':>6} Reason")
        print(f"  {'-'*5} {'-'*19} {'-'*6} {'-'*5} {'-'*5} {'-'*6} {'-'*6} {'-'*30}")
        for r in disagreements[-20:]:
            print(
                f"  {r['id']:>5} "
                f"{str(r['timestamp'])[:19]:<19} "
                f"{str(r['symbol']):<6} "
                f"{str(r['action']):<5} "
                f"{str(bool(r['approved'])):<5} "
                f"{str(bool(r['trader_brain_approved'])):<6} "
                f"{float(r['trader_brain_score'] or 0):>6.1f} "
                f"{str(r['trader_brain_reason'] or r['rejection_reason'] or '')[:80]}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
