#!/usr/bin/env python3
"""Refresh external-symbol research candidates from event discovery.

This pipeline can queue and backfill non-approved symbols for research, but it
does not add them to SYMBOL_CONFIG and does not change trading authority.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.external_symbol_candidate_service import (  # noqa: E402
    DEFAULT_MIN_BAR_DAYS,
    DEFAULT_MIN_BAR_ROWS,
    DEFAULT_MIN_CONFIDENCE_SCORE,
    DEFAULT_MIN_MENTIONS,
    DEFAULT_MIN_TRUSTED_MENTIONS,
    DEFAULT_POOL_REVIEW_SCORE,
    DEFAULT_STATE_PATH,
    ExternalSymbolCandidateService,
)
from services.ops_checks.external_symbol_discovery_checks import (  # noqa: E402
    build_external_symbol_discovery_payload,
)


def _run_backfill(args: argparse.Namespace, symbols: list[str]) -> int:
    if not symbols:
        return 0
    cmd = [
        sys.executable,
        str(BASE_DIR / "pipeline" / "historical_bar_backfill.py"),
        "--start-date",
        args.backfill_start_date,
        "--end-date",
        args.backfill_end_date or args.date,
        "--symbol",
        ",".join(symbols),
        "--chunk-days",
        str(args.backfill_chunk_days),
        "--horizon-bars",
        str(args.backfill_horizon_bars),
        "--skip-existing-cache",
        "--retry-attempts",
        str(args.backfill_retry_attempts),
        "--retry-sleep-seconds",
        str(args.backfill_retry_sleep_seconds),
        "--request-sleep-seconds",
        str(args.backfill_request_sleep_seconds),
    ]
    if args.max_chunks:
        cmd.extend(["--max-chunks", str(args.max_chunks)])
    print("Running external-symbol candidate historical backfill:")
    print("  " + " ".join(cmd))
    return int(subprocess.run(cmd, cwd=BASE_DIR).returncode)


def _default_start(target_date: str, lookback_days: int) -> str:
    parsed = date.fromisoformat(target_date)
    return (parsed - timedelta(days=max(0, lookback_days - 1))).isoformat()


def _print_human(payload: dict) -> None:
    print(f"report_version       : {payload.get('report_version')}")
    print(f"runtime_effect       : {payload.get('runtime_effect')}")
    print(f"status               : {payload.get('status')}")
    print(f"state_path           : {payload.get('state_path')}")
    print(f"discovery_window     : {payload.get('discovery_start_date')}..{payload.get('discovery_end_date')}")
    print(f"candidates_seen      : {payload.get('candidates_seen')}")
    print(f"backfill_symbols     : {', '.join(payload.get('backfill_symbols') or []) or '-'}")
    if payload.get("backfill_exit_code") is not None:
        print(f"backfill_exit_code   : {payload.get('backfill_exit_code')}")
    print()
    print("Candidates")
    for row in payload.get("candidates") or []:
        cov = row.get("coverage") or {}
        print(
            f"  {row.get('symbol'):<6} {row.get('status'):<34} "
            f"score={float(row.get('confidence_score') or 0):>5.1f} "
            f"mentions={int(row.get('mentions') or 0):>3} "
            f"trusted={int(row.get('trusted_mentions') or 0):>3} "
            f"rows={int(cov.get('rows') or 0):>7} "
            f"days={int(cov.get('trading_days') or 0):>4}"
        )
        print(f"         reason: {row.get('status_reason')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--discovery-start-date")
    parser.add_argument("--discovery-end-date")
    parser.add_argument("--lookback-days", type=int, default=5)
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--db-path", default=str(BASE_DIR / "trades.db"))
    parser.add_argument("--min-mentions", type=int, default=DEFAULT_MIN_MENTIONS)
    parser.add_argument("--min-trusted-mentions", type=int, default=DEFAULT_MIN_TRUSTED_MENTIONS)
    parser.add_argument("--min-bar-rows", type=int, default=DEFAULT_MIN_BAR_ROWS)
    parser.add_argument("--min-bar-days", type=int, default=DEFAULT_MIN_BAR_DAYS)
    parser.add_argument("--min-confidence-score", type=float, default=DEFAULT_MIN_CONFIDENCE_SCORE)
    parser.add_argument("--pool-review-score", type=float, default=DEFAULT_POOL_REVIEW_SCORE)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--no-auto-backfill", action="store_true")
    parser.add_argument("--backfill-start-date", default="2024-06-01")
    parser.add_argument("--backfill-end-date")
    parser.add_argument("--backfill-chunk-days", type=int, default=30)
    parser.add_argument("--backfill-horizon-bars", type=int, default=20)
    parser.add_argument("--backfill-request-sleep-seconds", type=float, default=0.25)
    parser.add_argument("--backfill-retry-attempts", type=int, default=2)
    parser.add_argument("--backfill-retry-sleep-seconds", type=float, default=15.0)
    parser.add_argument("--max-chunks", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    discovery_start = args.discovery_start_date or _default_start(args.date, args.lookback_days)
    discovery_end = args.discovery_end_date or args.date
    discovery = build_external_symbol_discovery_payload(
        base_dir=BASE_DIR,
        start_date=discovery_start,
        end_date=discovery_end,
        min_mentions=args.min_mentions,
        limit=args.limit,
    )

    service = ExternalSymbolCandidateService(
        state_path=args.state_path,
        db_path=args.db_path,
    )
    result = service.refresh_from_discovery(
        discovery,
        min_mentions=args.min_mentions,
        min_trusted_mentions=args.min_trusted_mentions,
        min_bar_rows=args.min_bar_rows,
        min_bar_days=args.min_bar_days,
        min_confidence_score=args.min_confidence_score,
        pool_review_score=args.pool_review_score,
        persist=not args.dry_run,
    )
    payload = result.to_dict()

    if payload["backfill_symbols"] and not args.no_auto_backfill:
        if args.dry_run:
            payload["status"] = "would_backfill_candidates"
        else:
            exit_code = _run_backfill(args, payload["backfill_symbols"])
            payload["backfill_exit_code"] = exit_code
            refreshed = service.refresh_from_discovery(
                discovery,
                min_mentions=args.min_mentions,
                min_trusted_mentions=args.min_trusted_mentions,
                min_bar_rows=args.min_bar_rows,
                min_bar_days=args.min_bar_days,
                min_confidence_score=args.min_confidence_score,
                pool_review_score=args.pool_review_score,
                persist=True,
            )
            payload = refreshed.to_dict()
            payload["backfill_exit_code"] = exit_code

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
