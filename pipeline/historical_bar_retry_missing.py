#!/usr/bin/env python3
"""Build or run a focused Polygon historical-bar retry plan.

The broad backfill job is appropriate for the first pass. This helper is for
the tail: symbols still below the day floor and symbols tied to recent manifest
errors. It defaults to dry-run and never changes live trading authority.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.ops_checks.historical_bar_progress_checks import (  # noqa: E402
    DEFAULT_MANIFEST_DIR,
    _cache_symbol_progress,
    _load_manifests,
)
from symbols_config import APPROVED_SYMBOLS_LIST  # noqa: E402


RETRY_PLAN_VERSION = "historical_bar_retry_plan_v1"
ERROR_SYMBOL_RE = re.compile(r"\b([A-Z]{1,5})\s+\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}:")
ENV_FILE = Path("/etc/trading-bot.env")


def _load_env_file(path: Path = ENV_FILE) -> bool:
    if not path.exists():
        return False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return True


def _error_symbols(errors: list[str]) -> list[str]:
    symbols: set[str] = set()
    approved = set(APPROVED_SYMBOLS_LIST)
    for error in errors:
        match = ERROR_SYMBOL_RE.search(error or "")
        if match and match.group(1) in approved:
            symbols.add(match.group(1))
    return sorted(symbols)


def build_retry_plan(
    *,
    base_dir: Path,
    start_date: str,
    end_date: str,
    min_days: int,
    max_symbols: int,
    manifest_limit: int,
) -> dict:
    cache_dir = base_dir / DEFAULT_MANIFEST_DIR.parent
    progress = _cache_symbol_progress(
        cache_dir,
        min_days=min_days,
        start_date=start_date,
        end_date=end_date,
    )
    incomplete = sorted(
        [row for row in progress if not row.get("ready")],
        key=lambda row: (int(row.get("market_dates") or 0), str(row.get("symbol"))),
    )
    manifests = _load_manifests(base_dir / DEFAULT_MANIFEST_DIR, limit=manifest_limit)
    recent_errors = [
        str(error)
        for manifest in manifests
        for error in (manifest.get("errors") or [])
    ]
    failed_symbols = _error_symbols(recent_errors)

    failed_symbol_set = set(failed_symbols)
    incomplete.sort(
        key=lambda row: (
            0 if str(row.get("symbol") or "") in failed_symbol_set else 1,
            int(row.get("market_dates") or 0),
            str(row.get("symbol") or ""),
        )
    )

    ordered: list[str] = []
    reasons: dict[str, list[str]] = {}
    for row in incomplete:
        symbol = str(row.get("symbol") or "")
        if symbol not in ordered:
            ordered.append(symbol)
        if symbol in failed_symbol_set:
            reasons.setdefault(symbol, []).append("recent_manifest_error")
        reasons.setdefault(symbol, []).append(
            f"below_day_floor:{int(row.get('market_dates') or 0)}/{min_days}"
        )
    for symbol in failed_symbols:
        if symbol not in ordered:
            ordered.append(symbol)
        reason_list = reasons.setdefault(symbol, [])
        if "recent_manifest_error" not in reason_list:
            reason_list.append("recent_manifest_error")

    selected = ordered[: max(1, max_symbols)]
    command = [
        sys.executable,
        str(base_dir / "pipeline" / "historical_bar_backfill.py"),
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--symbol",
        ",".join(selected),
        "--chunk-days",
        "30",
        "--skip-existing-cache",
        "--rebuild-patterns-for-existing-cache",
        "--request-sleep-seconds",
        "13",
        "--retry-attempts",
        "3",
        "--retry-sleep-seconds",
        "20",
    ] if selected else []

    return {
        "report_version": RETRY_PLAN_VERSION,
        "runtime_effect": "offline_backfill_retry_no_live_authority",
        "start_date": start_date,
        "end_date": end_date,
        "min_days": min_days,
        "manifest_limit": manifest_limit,
        "symbols_remaining": len(incomplete),
        "recent_manifest_errors": len(recent_errors),
        "failed_symbols": failed_symbols,
        "selected_symbols": selected,
        "selection_reasons": {symbol: reasons.get(symbol, []) for symbol in selected},
        "command": command,
    }


def _print_human(payload: dict, *, execute: bool) -> None:
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"date_filter             : {payload['start_date']}..{payload['end_date']}")
    print(f"min_days                : {payload['min_days']}")
    print(f"symbols_remaining       : {payload['symbols_remaining']}")
    print(f"recent_manifest_errors  : {payload['recent_manifest_errors']}")
    print(f"execute                 : {execute}")
    print()
    print("Selected symbols")
    if payload["selected_symbols"]:
        for symbol in payload["selected_symbols"]:
            print(f"  {symbol:<8} {', '.join(payload['selection_reasons'].get(symbol, []))}")
    else:
        print("  none")
    print()
    if payload["command"]:
        print("Retry command")
        print("  " + " ".join(payload["command"]))
    else:
        print("[OK] no retry command needed")


def main(argv: list[str] | None = None) -> int:
    _load_env_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--min-days", type=int, default=252)
    parser.add_argument("--max-symbols", type=int, default=10)
    parser.add_argument("--manifest-limit", type=int, default=10)
    parser.add_argument("--execute", action="store_true", help="Run the focused backfill command.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_retry_plan(
        base_dir=BASE_DIR,
        start_date=args.start_date,
        end_date=args.end_date,
        min_days=args.min_days,
        max_symbols=args.max_symbols,
        manifest_limit=args.manifest_limit,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(payload, execute=args.execute)

    if args.execute and payload["command"]:
        result = subprocess.run(payload["command"], cwd=BASE_DIR)
        return int(result.returncode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
