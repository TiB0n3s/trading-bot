#!/usr/bin/env python3
"""Archive Polygon 1-minute bars for approved symbols.

This is an offline/learning data job. It writes cached CSVs and, by default,
feeds bars into bar_pattern_features for candle-physics/triple-barrier learning.
It does not place orders or alter live authority.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from market_time import expected_market_context_date  # noqa: E402
from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository  # noqa: E402
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


def _next_date(value: str) -> str:
    return (date.fromisoformat(value) + timedelta(days=1)).isoformat()


def _existing_pattern_rows(
    *,
    db_path: Path,
    symbol: str,
    start_date: str,
    end_date: str,
) -> int:
    if not db_path.exists():
        return 0
    try:
        return BarPatternFeatureRepository(db_path).count_existing_1m_rows(
            symbol=symbol,
            start_ts=start_date,
            end_exclusive_ts=_next_date(end_date),
        )
    except Exception:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single date to archive, YYYY-MM-DD")
    parser.add_argument("--start-date", help="Start date, YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date, YYYY-MM-DD")
    parser.add_argument("--symbol", action="append", help="Symbol or comma-separated symbols")
    parser.add_argument("--all", action="store_true", help="Archive all approved symbols")
    parser.add_argument("--cache-dir")
    parser.add_argument("--db-path", default=str(ROOT / "trades.db"))
    parser.add_argument("--horizon-bars", type=int, default=20)
    parser.add_argument("--no-patterns", action="store_true")
    parser.add_argument(
        "--skip-existing-patterns",
        action="store_true",
        help="Treat existing same-day bar_pattern_features rows as success and avoid Polygon.",
    )
    parser.add_argument(
        "--min-existing-pattern-rows",
        type=int,
        default=1,
        help="Minimum existing 1m rows per symbol/date range required for --skip-existing-patterns.",
    )
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

    service: HistoricalBarArchiveService | None = None
    cache_dir = Path(args.cache_dir) if args.cache_dir else ROOT / DEFAULT_HISTORICAL_BAR_DIR
    db_path = Path(args.db_path)
    results = []
    rows_written = 0
    errors = []
    skipped_existing_patterns = 0
    for symbol in symbols:
        if args.skip_existing_patterns and not args.dry_run:
            existing_rows = _existing_pattern_rows(
                db_path=db_path,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
            if existing_rows >= args.min_existing_pattern_rows:
                skipped_existing_patterns += 1
                print(
                    "archive_skip "
                    f"symbol={symbol} start={start_date} end={end_date} "
                    f"reason=existing_pattern_rows rows={existing_rows}"
                )
                continue
        try:
            if service is None:
                service = HistoricalBarArchiveService()
            result = service.archive_polygon_1m_bars(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                cache_dir=cache_dir,
                db_path=db_path,
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
        "skipped_existing_pattern_symbols": skipped_existing_patterns,
        "rows_written": rows_written,
        "errors": errors,
    }
    print(json.dumps(summary, sort_keys=True))
    print(f"rows_written: {rows_written}")
    successful_or_existing = int(summary["successful_symbols"]) + skipped_existing_patterns
    coverage_rate = successful_or_existing / max(1, len(symbols))
    if errors and coverage_rate >= 0.80:
        print(
            "archive_warning: provider errors present but existing/successful "
            f"coverage is {coverage_rate:.2%}; treating as non-critical"
        )
        return 0
    return 0 if (results or skipped_existing_patterns) and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
