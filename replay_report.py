#!/usr/bin/env python3
"""
Replay Report.

Read-only report comparing original bot decisions against the current
deterministic trader-brain scorer.

Usage:
  python3 replay_report.py
  python3 replay_report.py --date 2026-05-26
  python3 replay_report.py --all
  python3 replay_report.py --limit 100
"""

import argparse
from datetime import date

from analytics_ext.replay_engine import replay_summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Date YYYY-MM-DD, default=today")
    parser.add_argument("--all", action="store_true", help="Replay all rows")
    parser.add_argument("--limit", type=int, help="Limit rows")
    args = parser.parse_args()

    date_prefix = None if args.all else (args.date or date.today().isoformat())
    summary = replay_summary(date_prefix=date_prefix, limit=args.limit)

    print("=" * 72)
    print("  Replay Report")
    print("=" * 72)
    print(f"date_prefix                  : {summary.get('date_prefix')}")
    print(f"total_rows                   : {summary.get('total_rows')}")
    print(f"replayable_rows              : {summary.get('replayable_rows')}")
    print(f"agreement                    : {summary.get('agreement')}")
    print(f"disagreement                 : {summary.get('disagreement')}")
    print(f"bot_approved_brain_rejected  : {summary.get('bot_approved_brain_rejected')}")
    print(f"bot_rejected_brain_approved  : {summary.get('bot_rejected_brain_approved')}")
    print(f"avg_score                    : {summary.get('avg_score')}")

    results = [r for r in summary.get("results", []) if r.get("replayable")]

    if not results:
        print()
        print("No replayable rows found.")
        return 0

    print()
    print("── Recent Disagreements ───────────────────────────────")
    disagreements = [r for r in results if not r.get("agreement")]

    if not disagreements:
        print("  No disagreements.")
    else:
        print(f"  {'ID':>5} {'Time':<19} {'Sym':<6} {'Act':<5} {'Orig':<6} {'Replay':<6} {'Score':>6} {'Setup':<18} Reason")
        print(f"  {'-'*5} {'-'*19} {'-'*6} {'-'*5} {'-'*6} {'-'*6} {'-'*6} {'-'*18} {'-'*30}")

        for r in disagreements[-25:]:
            print(
                f"  {str(r.get('id')):>5} "
                f"{str(r.get('timestamp'))[:19]:<19} "
                f"{str(r.get('symbol')):<6} "
                f"{str(r.get('action')):<5} "
                f"{str(r.get('original_approved')):<6} "
                f"{str(r.get('replay_approved')):<6} "
                f"{float(r.get('score') or 0):>6.1f} "
                f"{str(r.get('setup_type'))[:18]:<18} "
                f"{str(r.get('reason') or '')[:80]}"
            )

    print()
    print("── Recent Replay Rows ─────────────────────────────────")
    print(f"  {'ID':>5} {'Time':<19} {'Sym':<6} {'Act':<5} {'Orig':<6} {'Replay':<6} {'Score':>6} {'Setup':<18}")
    print(f"  {'-'*5} {'-'*19} {'-'*6} {'-'*5} {'-'*6} {'-'*6} {'-'*6} {'-'*18}")

    for r in results[-25:]:
        print(
            f"  {str(r.get('id')):>5} "
            f"{str(r.get('timestamp'))[:19]:<19} "
            f"{str(r.get('symbol')):<6} "
            f"{str(r.get('action')):<5} "
            f"{str(r.get('original_approved')):<6} "
            f"{str(r.get('replay_approved')):<6} "
            f"{float(r.get('score') or 0):>6.1f} "
            f"{str(r.get('setup_type'))[:18]:<18}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
