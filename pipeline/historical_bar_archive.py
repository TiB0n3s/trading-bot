#!/usr/bin/env python3
"""Archive Polygon 1-minute bars for approved symbols.

This is an offline/learning data job. It writes cached CSVs and, by default,
feeds bars into bar_pattern_features for candle-physics/triple-barrier learning.
It does not place orders or alter live authority.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_time import expected_market_context_date  # noqa: E402
from services.historical_bar_archive_service import (  # noqa: E402
    DEFAULT_HISTORICAL_BAR_DIR,
    HistoricalBarArchiveService,
)
from symbols_config import APPROVED_SYMBOLS_LIST  # noqa: E402


def _parse_symbols(values: list[str] | None, all_symbols: bool) -> list[str]:
    symbols: list[str] = []
    for value in values or []:
        symbols.extend(part.strip().upper() for part in value.split(",") if part.strip())
    if all_symbols:
        symbols.extend(APPROVED_SYMBOLS_LIST)
    return sorted(set(symbols))


def _result_payload(result) -> dict:
    if hasattr(result, "as_dict"):
        return result.as_dict()
    if is_dataclass(result):
        return asdict(result)
    if isinstance(result, dict):
        return result
    raise TypeError(f"Unsupported archive result type: {type(result)!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single date to archive, YYYY-MM-DD")
    parser.add_argument("--start-date", help="Start date, YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date, YYYY-MM-DD")
    parser.add_argument("--symbol", action="append", help="Symbol or comma-separated symbols")
    parser.add_argument("--all", action="store_true", help="Archive all approved symbols")
    parser.add_argument("--cache-dir")
    parser.add_argument("--horizon-bars", type=int, default=20)
    parser.add_argument("--no-patterns", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.date and (args.start_date or args.end_date):
        parser.error("Use --date or --start-date/--end-date, not both")
    if args.start_date and not args.end_date:
        parser.error("--start-date requires --end-date")
    if args.end_date and not args.start_date:
        parser.error("--end-date requires --start-date")

    start_date = args.date or args.start_date or expected_market_context_date().isoformat()
    end_date = args.date or args.end_date or start_date
    symbols = _parse_symbols(args.symbol, args.all)
    if not symbols:
        parser.error("Provide --symbol SYMBOL or --all")

    service = HistoricalBarArchiveService()
    cache_dir = Path(args.cache_dir) if args.cache_dir else ROOT / DEFAULT_HISTORICAL_BAR_DIR
    results = []
    rows_written = 0
    errors = []
    for symbol in symbols:
        try:
            result = service.archive_polygon_1m_bars(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                cache_dir=cache_dir,
                build_patterns=not args.no_patterns,
                horizon_bars=args.horizon_bars,
                dry_run=args.dry_run,
            )
            payload = _result_payload(result)
            results.append(payload)
            rows_written += int(payload.get("persisted_pattern_rows") or 0)
            errors.extend(payload.get("errors") or [])
            print(
                "archive_result "
                f"symbol={symbol} raw_bars={payload.get('raw_bars')} "
                f"regular_hours_bars={payload.get('regular_hours_bars')} "
                f"persisted_pattern_rows={payload.get('persisted_pattern_rows')} "
                f"errors={len(payload.get('errors') or [])}"
            )
        except Exception as exc:
            message = f"{symbol}: {type(exc).__name__}: {exc}"
            errors.append(message)
            print(f"[WARN] historical archive failed: {message}")

    summary = {
        "report_version": "historical_bar_archive_pipeline_v1",
        "runtime_effect": "offline_learning_archive_no_live_authority",
        "start_date": start_date,
        "end_date": end_date,
        "symbols": len(symbols),
        "successful_symbols": sum(1 for row in results if not row.get("errors")),
        "rows_written": rows_written,
        "errors": errors,
    }
    print(json.dumps(summary, sort_keys=True))
    print(f"rows_written: {rows_written}")
    return 0 if results and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
