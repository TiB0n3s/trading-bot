#!/usr/bin/env python3
"""Train the paper-only false-negative veto-relaxation model."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import default_market_date  # noqa: E402
from services.counterfactual_learning_service import train_from_repository  # noqa: E402


def _default_start(end_date: str, days: int) -> str:
    parsed = datetime.fromisoformat(end_date).date()
    return (parsed - timedelta(days=max(1, int(days)))).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=default_market_date())
    parser.add_argument("--start-date")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--db-path")
    parser.add_argument("--artifact-path")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--min-samples", type=int, default=30)
    args = parser.parse_args()

    artifact_kwargs = {}
    if args.artifact_path:
        artifact_kwargs["artifact_path"] = args.artifact_path
    result = train_from_repository(
        start_date=args.start_date or _default_start(args.date, args.lookback_days),
        end_date=args.date,
        db_path=args.db_path,
        limit=args.limit,
        min_samples=args.min_samples,
        **artifact_kwargs,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
