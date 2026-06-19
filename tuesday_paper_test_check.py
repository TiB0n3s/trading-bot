#!/usr/bin/env python3
"""
Tuesday paper-trading test checklist.

Read-only command wrapper for validating the bot before the next open session.
"""

import subprocess
import sys


COMMANDS = [
    ("Compile core files", [
        sys.executable, "-m", "py_compile",
        "app.py",
        "market_time.py",
        "trade_matcher.py",
        "trader_brain_report.py",
        "trader_brain_ops_check.py",
        "market_context_report.py",
        "strategy/trade_scorer.py",
        "strategy/trade_thesis.py",
        "market_intelligence/market_state.py",
    ]),
    ("DB integrity", ["sqlite3", "trades.db", "PRAGMA integrity_check;"]),
    ("Trade matcher", [sys.executable, "trade_matcher.py"]),
    ("Market context report", [sys.executable, "market_context_report.py"]),
    ("Trader brain ops check", [sys.executable, "trader_brain_ops_check.py"]),
    ("Analytics today", [sys.executable, "analytics_report.py"]),
    ("Trader brain report today", [sys.executable, "trader_brain_report.py"]),
]


def run(label, cmd):
    print()
    print("=" * 72)
    print(f"  {label}")
    print("=" * 72)
    result = subprocess.run(cmd, text=True)
    return result.returncode == 0


def main():
    ok = True

    for label, cmd in COMMANDS:
        if not run(label, cmd):
            ok = False

    print()
    print("=" * 72)
    if ok:
        print("[OK] Tuesday paper test checklist completed")
        return 0

    print("[WARN] one or more checks failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
