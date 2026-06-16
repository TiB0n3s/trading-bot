#!/usr/bin/env python3
"""Rebuild bar_pattern_features from local historical-bar CSV cache.

This is a no-Polygon-call repair path for stale persisted feature rows. It
replays cached 1-minute RTH CSV chunks through BarPatternFeatureService, which
upserts the current feature contract into bar_pattern_features.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository  # noqa: E402
from services.bar_pattern_feature_service import BarPatternFeatureService  # noqa: E402
from services.historical_bar_archive_service import DEFAULT_HISTORICAL_BAR_DIR  # noqa: E402
from symbols_config import APPROVED_SYMBOLS_LIST  # noqa: E402

FEATURE_REPAIR_VERSION = "historical_bar_feature_repair_v1"


def _parse_symbols(values: list[str] | None, all_symbols: bool) -> list[str]:
    symbols: list[str] = []
    for value in values or []:
        symbols.extend(part.strip().upper() for part in value.split(",") if part.strip())
    if all_symbols:
        symbols.extend(APPROVED_SYMBOLS_LIST)
    return sorted(set(symbols))


def _cache_chunks(
    cache_dir: Path,
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    latest_first: bool,
) -> list[Path]:
    paths = []
    marker = f"{symbol}_1min_rth_"
    for path in sorted(cache_dir.glob(f"{symbol}_1min_rth_????-??-??_????-??-??.csv")):
        stem = path.stem
        if not stem.startswith(marker):
            continue
        date_part = stem[len(marker) :]
        try:
            chunk_start, chunk_end = date_part.split("_", 1)
        except ValueError:
            continue
        if chunk_end < start_date or chunk_start > end_date:
            continue
        paths.append(path)
    return sorted(paths, reverse=latest_first)


def _row_to_bar(row: dict[str, str]) -> dict:
    timestamp = _utc_timestamp(row.get("Timestamp"))
    interval_start = _utc_timestamp(row.get("IntervalStart") or row.get("Timestamp"))
    return {
        "timestamp": timestamp,
        "interval_start": interval_start,
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


def _utc_timestamp(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _read_bars(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [_row_to_bar(row) for row in csv.DictReader(fh)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbol", action="append")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--cache-dir", default=str(BASE_DIR / DEFAULT_HISTORICAL_BAR_DIR))
    parser.add_argument(
        "--db-path",
        default=str(BASE_DIR / "trades.db"),
        help="SQLite target for repaired feature rows. Use an isolated research DB for large history.",
    )
    parser.add_argument("--horizon-bars", type=int, default=20)
    parser.add_argument("--max-chunks", type=int, default=0)
    parser.add_argument("--chunks-per-symbol", type=int, default=0)
    parser.add_argument("--oldest-first", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # Validate dates up front.
    date.fromisoformat(args.start_date)
    date.fromisoformat(args.end_date)

    symbols = _parse_symbols(args.symbol, args.all)
    if not symbols:
        parser.error("Provide --symbol SYMBOL or --all")

    cache_dir = Path(args.cache_dir)
    service = BarPatternFeatureService(BarPatternFeatureRepository(Path(args.db_path)))
    chunks_attempted = 0
    chunks_found = 0
    bars_read = 0
    feature_rows = 0
    persisted_rows = 0
    errors: list[str] = []
    per_symbol: dict[str, dict[str, int]] = {}

    for symbol in symbols:
        paths = _cache_chunks(
            cache_dir,
            symbol,
            args.start_date,
            args.end_date,
            latest_first=not args.oldest_first,
        )
        chunks_found += len(paths)
        per_symbol.setdefault(symbol, {"chunks": 0, "bars": 0, "features": 0, "persisted": 0})
        symbol_chunks_attempted = 0
        for path in paths:
            if args.max_chunks and chunks_attempted >= args.max_chunks:
                break
            if args.chunks_per_symbol and symbol_chunks_attempted >= args.chunks_per_symbol:
                break
            chunks_attempted += 1
            symbol_chunks_attempted += 1
            try:
                bars = _read_bars(path)
                result = service.persist_features(
                    bars,
                    symbol=symbol,
                    target_date=args.end_date,
                    timeframe="1m",
                    horizon_bars=args.horizon_bars,
                    bar_source="polygon_aggregate_1m_cache_repair",
                    adjusted=True,
                    interval_semantics="inclusive_start_regular_hours_1m",
                    dry_run=args.dry_run,
                )
                bars_read += len(bars)
                feature_rows += result.feature_rows
                persisted_rows += result.persisted_rows
                per_symbol[symbol]["chunks"] += 1
                per_symbol[symbol]["bars"] += len(bars)
                per_symbol[symbol]["features"] += result.feature_rows
                per_symbol[symbol]["persisted"] += result.persisted_rows
                print(
                    "feature_repair_chunk "
                    f"symbol={symbol} file={path.name} bars={len(bars)} "
                    f"features={result.feature_rows} persisted={result.persisted_rows}",
                    flush=True,
                )
            except Exception as exc:
                message = f"{symbol} {path.name}: {type(exc).__name__}: {exc}"
                errors.append(message)
                print(f"[WARN] {message}", flush=True)
        if args.max_chunks and chunks_attempted >= args.max_chunks:
            break

    payload = {
        "report_version": FEATURE_REPAIR_VERSION,
        "runtime_effect": "offline_feature_repair_no_live_authority",
        "db_path": str(Path(args.db_path)),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "symbols_requested": len(symbols),
        "chunks_found": chunks_found,
        "chunks_attempted": chunks_attempted,
        "bars_read": bars_read,
        "feature_rows": feature_rows,
        "persisted_rows": persisted_rows,
        "dry_run": args.dry_run,
        "errors": errors,
        "per_symbol": per_symbol,
    }
    print(json.dumps(payload, indent=2 if args.json else None, sort_keys=True))
    print(f"rows_written: {persisted_rows}")
    return 0 if chunks_attempted and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
