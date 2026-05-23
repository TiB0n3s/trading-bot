#!/usr/bin/env python3
"""
Post-session validation check — read-only after-market operational review.

Usage:
  python3 post_session_check.py
  python3 post_session_check.py 2026-05-08
"""

import subprocess
import sys
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from broker import api
from trade_matcher import rebuild_matched_trades

BASE_DIR = Path(__file__).resolve().parent
from db import DB_PATH, get_connection


def ok(msg):
    print(f"[OK]   {msg}")


def warn(msg):
    print(f"[WARN] {msg}")


def fail(msg):
    print(f"[FAIL] {msg}")


def run_cmd(label, cmd):
    print(f"\n── {label} ─────────────────────────────────────────")
    try:
        r = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.stdout.strip():
            print(r.stdout.rstrip())
        if r.stderr.strip():
            print(r.stderr.rstrip())
        if r.returncode == 0:
            ok(f"{label} completed")
            return True
        fail(f"{label} exited with code {r.returncode}")
        return False
    except Exception as e:
        fail(f"{label} failed: {e}")
        return False


def db_connect():
    return get_connection(DB_PATH)


def check_missing_fills(target_date):
    print("\n── Missing Fill Prices ─────────────────────────────")
    con = db_connect()
    rows = con.execute("""
        SELECT id, timestamp, symbol, action, order_id, order_status, qty, fill_price
        FROM trades
        WHERE timestamp LIKE ?
          AND approved = 1
          AND order_id IS NOT NULL
          AND qty IS NOT NULL
          AND fill_price IS NULL
        ORDER BY id DESC
    """, (f"{target_date}%",)).fetchall()
    con.close()

    if not rows:
        ok("No approved order rows missing fill_price for target date")
        return True

    warn(f"{len(rows)} approved order rows missing fill_price")
    for r in rows[:20]:
        print(
            f"  id={r['id']} {r['timestamp']} {r['symbol']} {r['action']} "
            f"status={r['order_status']} qty={r['qty']} order={str(r['order_id'])[:8]}"
        )
    print("  Suggested remediation: python3 backfill_missing_fills.py --dry-run")
    return False


def check_reconciliation():
    print("\n── Alpaca vs DB Reconciliation ─────────────────────")

    try:
        alpaca_positions = api.list_positions()
        alpaca = {p.symbol: float(p.qty) for p in alpaca_positions}
    except Exception as e:
        fail(f"Could not fetch Alpaca positions: {e}")
        return False

    con = db_connect()
    rows = con.execute("""
        SELECT symbol,
               SUM(CASE
                       WHEN LOWER(action) = 'buy'  THEN COALESCE(qty, 0)
                       WHEN LOWER(action) = 'sell' THEN -COALESCE(qty, 0)
                       ELSE 0
                   END) AS net_qty
        FROM trades
        WHERE order_id IS NOT NULL
          AND order_status IN ('filled', 'partially_filled')
        GROUP BY symbol
        HAVING net_qty > 0
        ORDER BY symbol
    """).fetchall()
    con.close()

    db_open = {r["symbol"]: float(r["net_qty"]) for r in rows if r["symbol"]}

    alpaca_syms = set(alpaca)
    db_syms = set(db_open)

    in_alpaca_not_db = sorted(alpaca_syms - db_syms)
    in_db_not_alpaca = sorted(db_syms - alpaca_syms)
    qty_mismatch = []

    for sym in sorted(alpaca_syms & db_syms):
        if abs(alpaca[sym] - db_open[sym]) > 0.0001:
            qty_mismatch.append((sym, alpaca[sym], db_open[sym]))

    print(f"Alpaca open symbols : {len(alpaca_syms)}")
    print(f"DB open symbols     : {len(db_syms)}")

    clean = True

    if in_alpaca_not_db:
        clean = False
        warn(f"Held in Alpaca but not open in DB: {in_alpaca_not_db}")

    if in_db_not_alpaca:
        clean = False
        warn(f"Open in DB but not held in Alpaca: {in_db_not_alpaca}")

    if qty_mismatch:
        clean = False
        warn("Quantity mismatches:")
        for sym, aq, dq in qty_mismatch:
            print(f"  {sym}: Alpaca={aq} DB={dq}")

    if clean:
        ok("Alpaca and DB open positions reconcile")
        return True

    return False


def check_fill_events(target_date):
    print("\n── Fill Events ─────────────────────────────────────")
    con = db_connect()
    try:
        rows = con.execute("""
            SELECT event, symbol, side, status, COUNT(*) AS n
            FROM fill_events
            WHERE timestamp LIKE ?
            GROUP BY event, symbol, side, status
            ORDER BY n DESC
            LIMIT 20
        """, (f"{target_date}%",)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()

    if not rows:
        warn("No fill_events rows found for target date")
        return True

    for r in rows:
        print(
            f"  {r['event']:<12} {str(r['symbol']):<6} "
            f"{str(r['side']):<5} {str(r['status']):<18} {r['n']:>4}"
        )
    ok("Fill events present")
    return True


def check_signal_counts(target_date):
    print("\n── Signal Counts ───────────────────────────────────")
    con = db_connect()
    row = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected,
            SUM(CASE WHEN order_id IS NOT NULL THEN 1 ELSE 0 END) AS orders
        FROM trades
        WHERE timestamp LIKE ?
    """, (f"{target_date}%",)).fetchone()
    con.close()

    total = row["total"] or 0
    approved = row["approved"] or 0
    rejected = row["rejected"] or 0
    orders = row["orders"] or 0

    print(f"Total signals : {total}")
    print(f"Approved      : {approved}")
    print(f"Rejected      : {rejected}")
    print(f"Orders        : {orders}")

    if total == 0:
        warn("No signals recorded for target date")
        return False

    ok("Signal counts loaded")
    return True


def rebuild_matches():
    print("\n── Matched Trades Rebuild ──────────────────────────")
    try:
        matched, open_lots = rebuild_matched_trades()
        ok(f"matched_trades rebuilt; matched={len(matched)} open_symbols={sum(1 for lots in open_lots.values() if lots)}")
        return True
    except Exception as e:
        fail(f"matched_trades rebuild failed: {e}")
        return False


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

    print("=" * 64)
    print(f"  Post-Session Check — {target_date}")
    print("=" * 64)

    checks = []

    checks.append(check_signal_counts(target_date))
    checks.append(check_missing_fills(target_date))
    checks.append(rebuild_matches())
    checks.append(check_reconciliation())
    checks.append(check_fill_events(target_date))

    # These scripts are read-only/reporting. They can be a little verbose.
    checks.append(run_cmd("Daily Summary", [sys.executable, "daily_summary.py", target_date]))
    checks.append(run_cmd("Filter Report", [sys.executable, "filter_report.py", "--date", target_date]))
    checks.append(run_cmd("Position Review", [sys.executable, "position_review.py"]))
    checks.append(run_cmd("Drawdown Report", [sys.executable, "drawdown_report.py", target_date]))
    checks.append(run_cmd("Analytics Report", [sys.executable, "analytics_report.py", "--date", target_date]))

    # Market-intelligence learning reports — read-only.
    checks.append(run_cmd("Daily Symbol Intelligence", [sys.executable, "intelligence_context_report.py", "--date", target_date]))
    checks.append(run_cmd("Event Attribution Report", [sys.executable, "event_attribution_report.py", "--date", target_date]))
    checks.append(run_cmd("Context Trade Join Report", [sys.executable, "context_trade_join_report.py", "--date", target_date, "--details", "--active-only"]))
    checks.append(run_cmd("Intelligence Learning Report", [sys.executable, "intelligence_learning_report.py", "--date", target_date]))
    checks.append(run_cmd("Intelligence Prediction Report", [sys.executable, "intelligence_prediction_report.py", "--date", target_date]))
    checks.append(run_cmd("Signal Timing Lesson Report", [sys.executable, "signal_timing_lesson_report.py", "--date", target_date]))

    print("\n" + "=" * 64)
    if all(checks):
        ok("Post-session check passed")
        return 0

    warn("Post-session check completed with warnings/issues")
    return 1


if __name__ == "__main__":
    sys.exit(main())
