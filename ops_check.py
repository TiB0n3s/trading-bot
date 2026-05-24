#!/usr/bin/env python3
"""
Operator check wrapper.

Usage:
  python3 ops_check.py morning
  python3 ops_check.py positions
  python3 ops_check.py alignment
  python3 ops_check.py adaptive
  python3 ops_check.py filters
  python3 ops_check.py drawdown
  python3 ops_check.py post
  python3 ops_check.py events
  python3 ops_check.py all
  python3 ops_check.py filters 2026-05-08
"""

import subprocess
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


COMMANDS = {
    "morning": ["morning_check.py"],
    "positions": ["position_review.py"],
    "alignment": ["market_alignment_report.py"],
    "adaptive": ["adaptive_confirmation_report.py"],
    "adaptive_impact": ["adaptive_impact_report.py"],
    "strategy_intelligence": ["strategy_intelligence_report.py"],
    "blocked": ["blocked_signal_outcome_report.py", "--date"],
    "session": ["session_momentum.py", "--all"],
    "position-momentum": ["position_momentum_monitor.py"],
    "filters": ["filter_report.py", "--date"],
    "drawdown": ["drawdown_report.py"],
    "post": ["post_session_check.py"],
    "events": ["bot_events.py", "--limit", "25"],
}


def run(label, args):
    print()
    print("=" * 72)
    print(f"  {label}")
    print("=" * 72)

    try:
        r = subprocess.run(
            [sys.executable] + args,
            cwd=BASE_DIR,
            text=True,
            timeout=180,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"[FAIL] {label} failed: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2

    command = sys.argv[1].lower()
    target_date = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()

    if command == "all":
        checks = []
        checks.append(run("Morning Check", ["morning_check.py"]))
        checks.append(run("Position Review", ["position_review.py"]))
        checks.append(run("Market Alignment Report", ["market_alignment_report.py"]))
        checks.append(run("Session Momentum Refresh", ["session_momentum.py", "--all"]))
        checks.append(run("Position Momentum Monitor", ["position_momentum_monitor.py"]))
        checks.append(run("Adaptive Confirmation Report", ["adaptive_confirmation_report.py"]))
        checks.append(run("Adaptive Impact Report", ["adaptive_impact_report.py", target_date]))
        checks.append(run("Filter Report", ["filter_report.py", "--date", target_date]))
        checks.append(run("Blocked Signal Outcome Report", ["blocked_signal_outcome_report.py", "--date", target_date]))
        checks.append(run("Drawdown Report", ["drawdown_report.py", target_date]))
        checks.append(run("Post-Session Check", ["post_session_check.py", target_date]))

        print()
        print("=" * 72)
        if all(checks):
            print("[OK] all requested checks completed successfully")
            return 0

        print("[WARN] one or more checks reported issues")
        return 1

    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print()
        print(__doc__.strip())
        return 2

    args = COMMANDS[command]

    if command == "filters":
        args = ["filter_report.py", "--date", target_date]
    elif command == "blocked":
        args = ["blocked_signal_outcome_report.py", "--date", target_date]
    elif command in ("drawdown", "post", "adaptive_impact", "strategy_intelligence"):
        args = args + [target_date]

    ok = run(command.title(), args)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
