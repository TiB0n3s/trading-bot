#!/usr/bin/env python3
"""Chunked Polygon historical 1-minute bar backfill.

This is the operator entrypoint for building multi-month or multi-year
regular-hours Polygon bar history. It writes cached CSV chunks and persists the
derived bar_pattern_features used by observe-only ML training.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.historical_bar_archive_service import (  # noqa: E402
    DEFAULT_HISTORICAL_BAR_DIR,
    HistoricalBarArchiveService,
)
from services.bar_pattern_feature_service import BarPatternFeatureService  # noqa: E402
from services.polygon_market_data_service import PolygonMarketDataService  # noqa: E402
from symbols_config import APPROVED_SYMBOLS_LIST  # noqa: E402


BACKFILL_REPORT_VERSION = "historical_bar_backfill_v1"
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


def _parse_symbols(values: list[str] | None, all_symbols: bool) -> list[str]:
    symbols: list[str] = []
    for value in values or []:
        symbols.extend(part.strip().upper() for part in value.split(",") if part.strip())
    if all_symbols:
        symbols.extend(APPROVED_SYMBOLS_LIST)
    return sorted(set(symbols))


def _date_chunks(start: date, end: date, chunk_days: int) -> list[tuple[date, date]]:
    if end < start:
        raise ValueError("end date must be on or after start date")
    chunk_days = max(1, int(chunk_days))
    chunks: list[tuple[date, date]] = []
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=chunk_days - 1))
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def _result_payload(result) -> dict:
    if hasattr(result, "as_dict"):
        return result.as_dict()
    if is_dataclass(result):
        return asdict(result)
    if isinstance(result, dict):
        return result
    raise TypeError(f"Unsupported archive result type: {type(result)!r}")


def _cache_path(cache_dir: Path, symbol: str, start: date, end: date) -> Path:
    return cache_dir / f"{symbol}_1min_rth_{start.isoformat()}_{end.isoformat()}.csv"


def _cache_file_has_rows(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            next(fh, None)
            return next(fh, None) is not None
    except Exception:
        return False


def _cached_row_to_bar(row: dict[str, str]) -> dict[str, str | None]:
    return {
        "timestamp": row.get("Timestamp") or row.get("IntervalStart"),
        "interval_start": row.get("IntervalStart") or row.get("Timestamp"),
        "interval_semantics": row.get("IntervalSemantics") or "inclusive_start_regular_hours_1m",
        "source": row.get("Source") or "polygon_aggregate_1m_cache",
        "adjusted": row.get("Adjusted"),
        "open": row.get("Open"),
        "high": row.get("High"),
        "low": row.get("Low"),
        "close": row.get("Close"),
        "volume": row.get("Volume"),
        "vwap": row.get("VWAP") or row.get("Close"),
    }


def _read_cached_bars(path: Path) -> list[dict[str, str | None]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return [_cached_row_to_bar(row) for row in csv.DictReader(fh)]


def _write_manifest(cache_dir: Path, payload: dict) -> Path:
    manifest_dir = cache_dir / "backfill_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = manifest_dir / f"historical_bar_backfill_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    _load_env_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, help="Backfill start date, YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="Backfill end date, YYYY-MM-DD")
    parser.add_argument("--symbol", action="append", help="Symbol or comma-separated symbols")
    parser.add_argument("--all", action="store_true", help="Backfill all approved symbols")
    parser.add_argument("--cache-dir")
    parser.add_argument("--chunk-days", type=int, default=30)
    parser.add_argument("--horizon-bars", type=int, default=20)
    parser.add_argument("--no-patterns", action="store_true")
    parser.add_argument("--skip-existing-cache", action="store_true")
    parser.add_argument(
        "--rebuild-patterns-for-existing-cache",
        action="store_true",
        help="When --skip-existing-cache skips a populated CSV, rebuild DB pattern rows from that cache without calling Polygon.",
    )
    parser.add_argument("--max-chunks", type=int, default=0, help="Safety limit for smoke runs; 0 means all chunks")
    parser.add_argument("--request-sleep-seconds", type=float, default=0.0)
    parser.add_argument("--retry-attempts", type=int, default=2)
    parser.add_argument("--retry-sleep-seconds", type=float, default=15.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    symbols = _parse_symbols(args.symbol, args.all)
    if not symbols:
        parser.error("Provide --symbol SYMBOL or --all")

    cache_dir = Path(args.cache_dir) if args.cache_dir else ROOT / DEFAULT_HISTORICAL_BAR_DIR
    chunks = _date_chunks(start, end, args.chunk_days)
    service = HistoricalBarArchiveService(
        bar_pattern_service=BarPatternFeatureService(),
        polygon_market_data=PolygonMarketDataService(
            timeout_seconds=20.0,
            retry_attempts=args.retry_attempts,
            retry_sleep_seconds=args.retry_sleep_seconds,
        )
    )
    results: list[dict] = []
    errors: list[str] = []
    skipped_chunks = 0
    cache_repair_chunks = 0
    cache_repair_rows = 0
    attempted_chunks = 0
    persisted_rows = 0
    cached_rows = 0

    print(
        "historical_bar_backfill "
        f"start={start.isoformat()} end={end.isoformat()} symbols={len(symbols)} "
        f"chunks_per_symbol={len(chunks)} dry_run={args.dry_run}"
    )

    for symbol in symbols:
        for chunk_start, chunk_end in chunks:
            if args.max_chunks and attempted_chunks >= args.max_chunks:
                break
            cache_path = _cache_path(cache_dir, symbol, chunk_start, chunk_end)
            if args.skip_existing_cache and cache_path.exists() and _cache_file_has_rows(cache_path):
                skipped_chunks += 1
                if args.rebuild_patterns_for_existing_cache and not args.no_patterns:
                    try:
                        bars = _read_cached_bars(cache_path)
                        result = service.bar_pattern_service.persist_features(
                            bars,
                            symbol=symbol,
                            target_date=chunk_end.isoformat(),
                            timeframe="1m",
                            horizon_bars=args.horizon_bars,
                            bar_source="polygon_aggregate_1m_cache_repair",
                            adjusted=True,
                            interval_semantics="inclusive_start_regular_hours_1m",
                            dry_run=args.dry_run,
                        )
                        cache_repair_chunks += 1
                        cache_repair_rows += int(result.persisted_rows or 0)
                        persisted_rows += int(result.persisted_rows or 0)
                        print(
                            "archive_cache_repair "
                            f"symbol={symbol} start={chunk_start.isoformat()} "
                            f"end={chunk_end.isoformat()} bars={len(bars)} "
                            f"persisted_pattern_rows={result.persisted_rows}"
                        )
                    except Exception as exc:
                        message = (
                            f"{symbol} {chunk_start.isoformat()}..{chunk_end.isoformat()}: "
                            f"{type(exc).__name__}: cache feature repair failed: {exc}"
                        )
                        errors.append(message)
                        print(f"[WARN] archive_cache_repair_failed {message}")
                print(
                    "archive_skip "
                    f"symbol={symbol} start={chunk_start.isoformat()} "
                    f"end={chunk_end.isoformat()} reason=cache_exists"
                )
                continue
            if args.skip_existing_cache and cache_path.exists():
                print(
                    "archive_retry "
                    f"symbol={symbol} start={chunk_start.isoformat()} "
                    f"end={chunk_end.isoformat()} reason=empty_or_unreadable_cache"
                )

            attempted_chunks += 1
            try:
                result = service.archive_polygon_1m_bars(
                    symbol=symbol,
                    start_date=chunk_start,
                    end_date=chunk_end,
                    cache_dir=cache_dir,
                    build_patterns=not args.no_patterns,
                    horizon_bars=args.horizon_bars,
                    dry_run=args.dry_run,
                )
                payload = _result_payload(result)
                results.append(payload)
                persisted_rows += int(payload.get("persisted_pattern_rows") or 0)
                cached_rows += int(payload.get("cached_rows") or 0)
                errors.extend(payload.get("errors") or [])
                print(
                    "archive_chunk "
                    f"symbol={symbol} start={chunk_start.isoformat()} "
                    f"end={chunk_end.isoformat()} regular_hours_bars={payload.get('regular_hours_bars')} "
                    f"persisted_pattern_rows={payload.get('persisted_pattern_rows')} "
                    f"errors={len(payload.get('errors') or [])}"
                )
                if args.request_sleep_seconds > 0:
                    time.sleep(args.request_sleep_seconds)
            except Exception as exc:
                message = (
                    f"{symbol} {chunk_start.isoformat()}..{chunk_end.isoformat()}: "
                    f"{type(exc).__name__}: {exc}"
                )
                errors.append(message)
                print(f"[WARN] archive_chunk_failed {message}")
                if args.request_sleep_seconds > 0:
                    time.sleep(args.request_sleep_seconds)
        if args.max_chunks and attempted_chunks >= args.max_chunks:
            break

    summary = {
        "report_version": BACKFILL_REPORT_VERSION,
        "runtime_effect": "offline_learning_archive_no_live_authority",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "symbols_requested": len(symbols),
        "chunks_per_symbol": len(chunks),
        "attempted_chunks": attempted_chunks,
        "skipped_chunks": skipped_chunks,
        "cache_repair_chunks": cache_repair_chunks,
        "cache_repair_rows": cache_repair_rows,
        "successful_chunks": sum(1 for row in results if not row.get("errors")),
        "cached_rows": cached_rows,
        "persisted_pattern_rows": persisted_rows,
        "build_patterns": not args.no_patterns,
        "dry_run": args.dry_run,
        "errors": errors,
    }
    if not args.dry_run:
        summary["manifest_path"] = str(_write_manifest(cache_dir, summary))
    print(json.dumps(summary, sort_keys=True))
    print(f"rows_written: {persisted_rows}")
    return 0 if (attempted_chunks or cache_repair_chunks or skipped_chunks) and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
