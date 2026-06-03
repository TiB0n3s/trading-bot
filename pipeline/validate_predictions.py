#!/usr/bin/env python3
"""Warn when recent prediction_score correlation is stale or negative.

This command is intended for the pre-market pipeline. It is warning-only and
always has no live trading authority.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.prediction_drift_service import build_default_prediction_drift_service


def _print_human(payload: dict) -> None:
    status = "WARN" if payload.get("warning") else "OK"
    print()
    print("=" * 72)
    print(f"Prediction validation drift check [{status}]")
    print("=" * 72)
    print(f"target_date              : {payload.get('target_date')}")
    print(f"sessions_requested       : {payload.get('sessions_requested')}")
    print(f"valid_session_count      : {payload.get('valid_session_count')}")
    print(f"bad_session_count        : {payload.get('bad_session_count')}")
    print(f"average_correlation      : {payload.get('average_correlation')}")
    print(f"retraining_recommended   : {payload.get('retraining_recommended')}")
    print(f"reason                   : {payload.get('reason')}")
    rows = payload.get("date_scores") or []
    if rows:
        print()
        print("Date          Pairs  Corr     Status")
        print("-" * 72)
        for row in rows:
            corr = row.get("correlation")
            corr_s = "n/a" if corr is None else f"{corr:.4f}"
            print(
                f"{row.get('market_date', ''):<12} "
                f"{row.get('pair_count', 0):>5}  "
                f"{corr_s:>7}  "
                f"{row.get('status', '')}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", dest="target_date")
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.0)
    parser.add_argument("--bad-session-limit", type=int, default=3)
    parser.add_argument("--min-pairs", type=int, default=3)
    parser.add_argument("--db-path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    service = build_default_prediction_drift_service(db_path=args.db_path)
    report = service.correlation_report(
        target_date=args.target_date,
        sessions=args.sessions,
        threshold=args.threshold,
        bad_session_limit=args.bad_session_limit,
        min_pairs_per_session=args.min_pairs,
    ).to_dict()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
