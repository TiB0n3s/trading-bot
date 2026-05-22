#!/usr/bin/env python3
"""
Filter effectiveness report — read-only rejection analytics.

Usage:
  python3 filter_report.py
  python3 filter_report.py --week
  python3 filter_report.py --all
  python3 filter_report.py --symbol QQQ
  python3 filter_report.py --date 2026-05-08
"""

import argparse
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from db import DB_PATH, get_connection

KNOWN_LABELS = {
    "market_hours": "Outside trading hours",
    "duplicate_webhook": "Duplicate webhook",
    "symbol_override": "Symbol override",
    "circuit_breaker": "Daily loss circuit breaker",
    "ghost_sell": "Ghost sell",
    "cooldown": "Cooldown",
    "churn_window": "Sell→buy churn window",
    "churn_price": "Sell→buy churn price",
    "daily_symbol_buy_limit": "Daily symbol buy limit",
    "exposure_cap": "Per-symbol exposure cap",
    "correlation_cap": "Correlation cluster cap",
    "trend_gate": "Trend gate",
    "trend_confirmation": "Trend confirmation",
    "fundamental_score": "Fundamental score gate",
    "macro_risk": "Macro risk",
    "macro_position_limit": "Macro position limit",
    "market_bias_avoid": "Market bias avoid",
    "soft_avoid_prediction_gate": "Soft avoid prediction gate",
    "live_bias_downgrade": "Live bias downgrade",
    "setup_policy": "Entry quality / setup policy",
    "chase_prevention": "Chase prevention",
    "addon_momentum_gate": "Add-on momentum gate",
    "session_momentum_gate": "Session momentum gate",
    "prediction_gate": "Prediction gate",
    "strategy_memory": "Strategy memory gate",
    "decision_policy": "Decision policy gate",
    "confidence_gate": "Low confidence gate",
    "second_look": "Second-look market check",
    "stale_signal": "Stale signal",
    "order_path_exception": "Order path exception",
    "cash_safe_symbol": "Cash-safe symbol block",
    "cash_safe_position_limit": "Cash-safe position limit",
    "cash_safe_daily_symbol_limit": "Cash-safe daily symbol limit",
    "cash_safe_confidence": "Cash-safe confidence gate",
}


def category(reason):
    if not reason:
        return "unknown"
    if ":" in reason:
        return reason.split(":", 1)[0].strip()
    return "claude_rejection"


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


def print_section(title):
    print()
    print("── " + title + " " + "─" * max(0, 64 - len(title)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Date YYYY-MM-DD, default=today")
    parser.add_argument("--week", action="store_true", help="Current week Monday-Friday")
    parser.add_argument("--all", action="store_true", help="All history")
    parser.add_argument("--symbol", help="Filter to one symbol")
    parser.add_argument("--limit", type=int, default=20, help="Recent sample rows to show")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"ERROR: {DB_PATH} not found")

    clause, params = date_clause(args)
    symbol_clause = ""
    if args.symbol:
        symbol_clause = "AND symbol = ?"
        params.append(args.symbol.upper())

    con = get_connection(DB_PATH)

    rows = con.execute(f"""
        SELECT id, timestamp, symbol, action, approved, rejection_reason,
               market_bias, risk_level, entry_quality,
               trend_direction, trend_strength,
               momentum_direction, momentum_pct,
               macro_regime, risk_multiplier,
               correlation_cluster, cluster_exposure_pct
        FROM trades
        WHERE approved = 0
          AND rejection_reason IS NOT NULL
          {clause}
          {symbol_clause}
        ORDER BY id DESC
    """, params).fetchall()

    total_signals = con.execute(f"""
        SELECT COUNT(*) AS n
        FROM trades
        WHERE 1=1
          {clause}
          {symbol_clause}
    """, params).fetchone()["n"]

    approved_signals = con.execute(f"""
        SELECT COUNT(*) AS n
        FROM trades
        WHERE approved = 1
          {clause}
          {symbol_clause}
    """, params).fetchone()["n"]

    rejected_signals = len(rows)

    print()
    print("=" * 72)
    print("  Filter Effectiveness Report")
    print("=" * 72)
    print(f"  Total signals      : {total_signals}")
    print(f"  Approved signals   : {approved_signals}")
    print(f"  Rejected signals   : {rejected_signals}")
    if total_signals:
        print(f"  Rejection rate     : {rejected_signals / total_signals * 100:.1f}%")
    if args.symbol:
        print(f"  Symbol filter      : {args.symbol.upper()}")

    by_cat = defaultdict(int)
    by_symbol = defaultdict(int)
    by_cat_symbol = defaultdict(lambda: defaultdict(int))

    for r in rows:
        cat = category(r["rejection_reason"])
        by_cat[cat] += 1
        by_symbol[r["symbol"]] += 1
        by_cat_symbol[cat][r["symbol"]] += 1

    print_section("Top rejection categories")
    if not by_cat:
        print("  No rejections in range.")
    else:
        print(f"  {'Category':<28} {'Label':<28} {'Count':>6}")
        print(f"  {'-'*28} {'-'*28} {'-'*6}")
        for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
            label = KNOWN_LABELS.get(cat, "Other / Claude")
            print(f"  {cat:<28} {label:<28} {n:>6}")

    print_section("Top rejected symbols")
    if not by_symbol:
        print("  No rejected symbols in range.")
    else:
        print(f"  {'Symbol':<8} {'Rejected':>8}")
        print(f"  {'-'*8} {'-'*8}")
        for sym, n in sorted(by_symbol.items(), key=lambda x: -x[1])[:20]:
            print(f"  {sym:<8} {n:>8}")

    print_section("Category × top symbols")
    if not by_cat_symbol:
        print("  No category/symbol data.")
    else:
        for cat, sym_counts in sorted(by_cat_symbol.items(), key=lambda x: -sum(x[1].values())):
            top = sorted(sym_counts.items(), key=lambda x: -x[1])[:8]
            joined = ", ".join(f"{sym}:{n}" for sym, n in top)
            print(f"  {cat:<28} {joined}")

    print_section("Recent rejection samples")
    if not rows:
        print("  No recent samples.")
    else:
        print(f"  {'ID':>5} {'Time':<19} {'Sym':<6} {'Act':<5} {'Category':<24} Reason")
        print(f"  {'-'*5} {'-'*19} {'-'*6} {'-'*5} {'-'*24} {'-'*40}")
        for r in rows[: args.limit]:
            reason = r["rejection_reason"] or ""
            cat = category(reason)
            detail = reason.split(":", 1)[1].strip() if ":" in reason else reason
            print(
                f"  {r['id']:>5} {r['timestamp']:<19} {r['symbol']:<6} "
                f"{r['action']:<5} {cat:<24} {detail[:80]}"
            )

    con.close()


if __name__ == "__main__":
    main()
