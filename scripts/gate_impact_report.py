#!/usr/bin/env python3
"""Trace-native gate impact report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.decision.trace_reports import gate_impact_summary, load_trace_rows

DB_PATH = Path(__file__).resolve().parents[1] / "trades.db"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = load_trace_rows(db_path=DB_PATH, target_date=args.date, limit=args.limit)
    payload = {
        "report_version": "gate_impact_report_v1",
        "runtime_effect": "trace_report_only_no_runtime_authority",
        "date": args.date,
        "rows": len(rows),
        "gate_impact": gate_impact_summary(rows),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0
    print("=" * 72)
    print("  Gate Impact Report")
    print("=" * 72)
    print(f"date                    : {args.date}")
    print(f"rows                    : {len(rows)}")
    for gate_id, counts in payload["gate_impact"].items():
        print(f"{gate_id:<24}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
