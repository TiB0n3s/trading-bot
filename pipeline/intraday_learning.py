#!/usr/bin/env python3
"""Intraday performance learning checkpoint.

This job creates an auditable same-day performance snapshot and writes it into
the auto-buy intraday feedback surface consumed by later candidate scans.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from services.intraday_trade_feedback_service import IntradayTradeFeedbackService  # noqa: E402

REPORT_DIR = ROOT / "reports" / "intraday_learning"


def _target_date(value: str | None) -> str:
    return value or datetime.now().strftime("%Y-%m-%d")


def _write_report(snapshot: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    phase = str(snapshot.get("phase") or "intraday").replace("/", "_")
    target_date = str(snapshot.get("target_date"))
    path = REPORT_DIR / f"{target_date}_{phase}.json"
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="Market date YYYY-MM-DD; defaults to today")
    parser.add_argument("--phase", default="noon", help="Snapshot phase, e.g. noon or post_fill")
    parser.add_argument("--symbol", default=None, help="Optional trigger symbol")
    parser.add_argument(
        "--no-historical",
        action="store_true",
        help="Use same-day closed trades only instead of adding recent matched-trade history",
    )
    parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Persist feedback event only; skip JSON report artifact",
    )
    args = parser.parse_args(argv)

    target_date = _target_date(args.date)
    service = IntradayTradeFeedbackService()
    snapshot = service.capture_performance_snapshot(
        target_date,
        phase=args.phase,
        trigger_symbol=args.symbol,
        include_historical=not args.no_historical,
    )
    report_path = None if args.no_write_report else _write_report(snapshot)

    print("Intraday learning checkpoint")
    print(f"  date              : {snapshot['target_date']}")
    print(f"  phase             : {snapshot['phase']}")
    print(f"  status            : {snapshot['status']}")
    print(f"  closed_trades     : {snapshot['same_day_closed_trades']}")
    print(f"  win_rate          : {snapshot['same_day_win_rate']}")
    print(f"  avg_pnl_pct       : {snapshot['same_day_avg_pnl_pct']}")
    print(f"  evidence_keys     : {snapshot['evidence_keys']}")
    print(f"  status_counts     : {snapshot['status_counts']}")
    if report_path:
        print(f"  report            : {report_path}")
    top_feedback = snapshot.get("top_feedback") or []
    if top_feedback:
        print("Top feedback")
        for item in top_feedback[:5]:
            print(
                "  "
                f"{item.get('status')} {item.get('key')} "
                f"trades={item.get('trades')} loss_rate={item.get('loss_rate')} "
                f"avg_pnl={item.get('avg_pnl_pct')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
