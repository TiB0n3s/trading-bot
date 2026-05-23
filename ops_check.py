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
  python3 ops_check.py intelligence
  python3 ops_check.py events
  python3 ops_check.py context
  python3 ops_check.py learning
  python3 ops_check.py predictions
  python3 ops_check.py signal-lessons
  python3 ops_check.py trends
  python3 ops_check.py prediction-validation
  python3 ops_check.py historical-backfill START_DATE END_DATE
  python3 ops_check.py all
  python3 ops_check.py filters 2026-05-08
  python3 ops_check.py events 2026-05-26
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
    "filters": ["filter_report.py", "--date"],
    "drawdown": ["drawdown_report.py"],
    "post": ["post_session_check.py"],
    "intelligence": ["intelligence_context_report.py", "--date"],
    "events": ["event_attribution_report.py", "--date"],
    "context": ["context_trade_join_report.py", "--date"],
    "learning": ["intelligence_learning_report.py", "--date"],
    "predictions": ["intelligence_prediction_report.py", "--date"],
    "signal-lessons": ["signal_timing_lesson_report.py", "--date"],
    "trends": ["trend_context_report.py", "--date"],
    "prediction-validation": ["prediction_validation_report.py", "--date"],
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


def args_for_command(command, target_date):
    args = COMMANDS[command]

    if command == "filters":
        return ["filter_report.py", "--date", target_date]

    if command in ("drawdown", "post"):
        return args + [target_date]

    if command in ("intelligence", "events", "context", "learning", "predictions", "signal-lessons", "trends", "prediction-validation"):
        return [args[0], "--date", target_date]

    return args


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2

    command = sys.argv[1].lower()
    target_date = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()

    if command == "historical-backfill":
        if len(sys.argv) < 4:
            print("Usage: python3 ops_check.py historical-backfill START_DATE END_DATE")
            return 2

        ok = run(
            "Historical Learning Backfill",
            [
                "historical_learning_backfill.py",
                "--start-date",
                sys.argv[2],
                "--end-date",
                sys.argv[3],
            ],
        )
        return 0 if ok else 1

    if command == "all":
        checks = []
        checks.append(run("Morning Check", ["morning_check.py"]))
        checks.append(run("Position Review", ["position_review.py"]))
        checks.append(run("Market Alignment Report", ["market_alignment_report.py"]))
        checks.append(run("Adaptive Confirmation Report", ["adaptive_confirmation_report.py"]))
        checks.append(run("Filter Report", ["filter_report.py", "--date", target_date]))
        checks.append(run("Drawdown Report", ["drawdown_report.py", target_date]))
        checks.append(run("Post-Session Check", ["post_session_check.py", target_date]))
        checks.append(run("Daily Symbol Intelligence", ["intelligence_context_report.py", "--date", target_date]))
        checks.append(run("Event Attribution Report", ["event_attribution_report.py", "--date", target_date]))
        checks.append(run("Context Trade Join Report", ["context_trade_join_report.py", "--date", target_date]))
        checks.append(run("Intelligence Learning Report", ["intelligence_learning_report.py", "--date", target_date]))
        checks.append(run("Intelligence Prediction Report", ["intelligence_prediction_report.py", "--date", target_date]))
        checks.append(run("Signal Timing Lesson Report", ["signal_timing_lesson_report.py", "--date", target_date]))
        checks.append(run("Trend Context Report", ["trend_context_report.py", "--date", target_date]))
        checks.append(run("Prediction Validation Report", ["prediction_validation_report.py", "--date", target_date]))

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

    ok = run(command.title(), args_for_command(command, target_date))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
