#!/usr/bin/env python3
"""Materialize and report best/good entry and exit timing labels.

The labels are derived from bar_pattern_features forward path outcomes. This is
learning evidence only; it does not approve, reject, size, or route orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    path_s = str(path)
    if path_s not in sys.path:
        sys.path.insert(0, path_s)

from services.bar_timing_quality_service import build_default_bar_timing_quality_service


def _print_table(title: str, rows: list[dict]) -> None:
    print()
    print("-" * 88)
    print(title)
    print("-" * 88)
    print(f"{'Label':<18} {'Rows':>8} {'AvgScore':>10} {'Fwd%':>10} {'MFE%':>10} {'MAE%':>10}")
    for row in rows:
        print(
            f"{str(row.get('label')):<18} "
            f"{int(row.get('rows') or 0):>8} "
            f"{float(row.get('avg_score') or 0):>10.2f} "
            f"{float(row.get('avg_forward_return_pct') or 0):>10.3f} "
            f"{float(row.get('avg_forward_mfe_pct') or 0):>10.3f} "
            f"{float(row.get('avg_forward_mae_pct') or 0):>10.3f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="Market date YYYY-MM-DD")
    group.add_argument("--all", action="store_true", help="All available bar-pattern rows")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    target_date = None if args.all else args.date
    result = build_default_bar_timing_quality_service().materialize(
        target_date=target_date,
        limit=args.limit,
        timeframe=args.timeframe,
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("=" * 88)
    print("Bar Timing Quality Report")
    print("=" * 88)
    print(f"target_date    : {target_date or 'ALL'}")
    print(f"timeframe      : {result['timeframe']}")
    print(f"source_rows    : {result['source_rows']}")
    print(f"rows_written   : {result['rows_written']}")
    print(f"label_version  : {result['label_version']}")
    print(f"runtime_effect : {result['runtime_effect']}")
    summary = result["summary"]
    print(f"persisted_rows : {summary['rows']}")
    _print_table("Entry Timing Labels", summary["entry_labels"])
    _print_table("Exit Timing Labels", summary["exit_labels"])
    print(f"rows_written: {result['rows_written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
