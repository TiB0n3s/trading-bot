#!/usr/bin/env python3
"""Write PSI concept-drift guardrail artifact for veto relaxation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import default_market_date  # noqa: E402
from services.concept_drift_service import build_default_concept_drift_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=default_market_date())
    parser.add_argument("--baseline-start", default="2024-06-01")
    parser.add_argument("--recent-days", type=int, default=5)
    parser.add_argument("--db-path")
    parser.add_argument("--artifact-path")
    parser.add_argument("--severe-threshold", type=float, default=0.25)
    args = parser.parse_args()

    service = build_default_concept_drift_service(db_path=args.db_path)
    kwargs = {}
    if args.artifact_path:
        kwargs["artifact_path"] = args.artifact_path
    report = service.psi_report(
        target_date=args.date,
        baseline_start=args.baseline_start,
        recent_days=args.recent_days,
        severe_threshold=args.severe_threshold,
        **kwargs,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
