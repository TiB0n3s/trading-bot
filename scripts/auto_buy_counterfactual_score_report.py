#!/usr/bin/env python3
"""No-write auto-buy scoring counterfactual report.

Examples:
  python3 scripts/auto_buy_counterfactual_score_report.py --date 2026-06-30
  python3 scripts/auto_buy_counterfactual_score_report.py --input-csv audit.csv --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
for path in (BASE_DIR / "scripts", BASE_DIR / "src", BASE_DIR):
    path_s = str(path)
    if path_s not in sys.path:
        sys.path.insert(0, path_s)

from trading_bot.persistence.repositories.auto_buy_counterfactual_score_repo import (  # noqa: E402
    load_auto_buy_rows_for_counterfactual_score,
)
from trading_bot.services.auto_buy_counterfactual_scoring_service import (  # noqa: E402
    ScoreReplayConfig,
    load_rows_from_csv,
    replay_counterfactual_scores,
)


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _render(payload: dict) -> bool:
    print("=" * 88)
    print("  Auto-Buy Counterfactual Score Replay")
    print("=" * 88)
    print(f"report_version   : {payload['report_version']}")
    print(f"runtime_effect   : {payload['runtime_effect']}")
    print(f"rows             : {payload['row_count']}")
    print(f"scored_rows      : {payload['scored_rows']}")
    print(f"outcome_field    : {payload['outcome_field']}")
    print(f"strong_threshold : {payload['strong_threshold']}")
    print()
    print("variant                              rows changed unlocks prof loss hardblk avg_ret")
    for row in payload["variants"]:
        print(
            f"{row['variant']:<36} "
            f"{row['rows']:>4} "
            f"{row['changed_rows']:>7} "
            f"{row['score_unlocks']:>7} "
            f"{row['profitable_unlocks']:>4} "
            f"{row['losing_unlocks']:>4} "
            f"{row['still_hard_blocked_unlocks']:>7} "
            f"{_fmt(row['avg_unlock_return_pct']):>7}"
        )
    print()
    print("[OK] counterfactual score replay completed; no live authority changed")
    return payload["scored_rows"] > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--db-path", default=str(BASE_DIR / "trades.db"))
    parser.add_argument("--input-csv")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--strong-threshold", type=float, default=13.0)
    parser.add_argument("--watch-threshold", type=float, default=7.0)
    parser.add_argument("--outcome-field", default="return_60m")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.input_csv:
        rows = load_rows_from_csv(args.input_csv)
    else:
        rows = load_auto_buy_rows_for_counterfactual_score(
            args.date,
            db_path=args.db_path,
            limit=args.limit,
        )
    payload = replay_counterfactual_scores(
        rows,
        config=ScoreReplayConfig(
            strong_threshold=args.strong_threshold,
            watch_threshold=args.watch_threshold,
            outcome_field=args.outcome_field,
        ),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0 if payload["scored_rows"] > 0 else 1
    return 0 if _render(payload) else 1


if __name__ == "__main__":
    raise SystemExit(main())
