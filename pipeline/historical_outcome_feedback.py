#!/usr/bin/env python3
"""Materialize prior-session trade outcomes for active paper intelligence."""

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

REPORT_DIR = ROOT / "reports" / "historical_outcome_feedback"


def _target_date(value: str | None) -> str:
    return value or datetime.now().strftime("%Y-%m-%d")


def _write_report(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{payload['target_date']}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="Market date YYYY-MM-DD; defaults to today")
    parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Persist database feedback only; skip JSON report artifact",
    )
    args = parser.parse_args(argv)

    service = IntradayTradeFeedbackService()
    payload = service.refresh_historical_outcome_feedback(_target_date(args.date))
    report_path = None if args.no_write_report else _write_report(payload)

    print("Historical outcome feedback refresh")
    print(f"  date              : {payload['target_date']}")
    print(f"  lookback_days     : {payload['lookback_days']}")
    print(f"  matched_rows      : {payload['matched_trade_rows']}")
    print(f"  evidence_rows     : {payload['evidence_rows']}")
    print(f"  persisted_rows    : {payload['persisted_rows']}")
    print(f"  status_counts     : {payload['status_counts']}")
    if report_path:
        print(f"  report            : {report_path}")
    top_feedback = payload.get("top_feedback") or []
    if top_feedback:
        print("Top persisted feedback")
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
