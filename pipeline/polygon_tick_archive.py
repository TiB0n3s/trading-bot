#!/usr/bin/env python3
"""Probe/archive Polygon tick-level stock trades for future tick-bar learning.

This is offline research storage only. It does not alter live trading authority.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, asdict
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.polygon_market_data_service import PolygonMarketDataService  # noqa: E402


TICK_ARCHIVE_VERSION = "polygon_tick_archive_v1"
DEFAULT_TICK_ARCHIVE_DIR = Path("data") / "historical_ticks" / "polygon_trades"


@dataclass(frozen=True)
class TickArchiveResult:
    report_version: str
    runtime_effect: str
    symbol: str
    target_date: str
    cache_path: str
    trades: int
    dry_run: bool
    errors: list[str]


def archive_polygon_trades(
    *,
    symbol: str,
    target_date: str | date,
    cache_dir: Path,
    limit: int = 50000,
    dry_run: bool = False,
    polygon_market_data: PolygonMarketDataService | None = None,
) -> TickArchiveResult:
    symbol = str(symbol or "").upper().strip()
    target = str(target_date)[:10]
    if not symbol:
        raise ValueError("symbol is required")
    service = polygon_market_data or PolygonMarketDataService(
        timeout_seconds=20.0,
        retry_attempts=2,
        retry_sleep_seconds=15.0,
    )
    cache_dir = Path(cache_dir)
    cache_path = cache_dir / f"{symbol}_trades_{target}.csv"
    errors: list[str] = []
    trades: list[dict] = []
    try:
        trades = service.trade_dicts(symbol, timestamp=target, limit=limit)
    except Exception as exc:
        errors.append(f"{symbol} {target}: {type(exc).__name__}: {exc}")

    if trades and not dry_run:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "timestamp",
                    "price",
                    "size",
                    "exchange",
                    "conditions",
                    "sequence_number",
                    "tape",
                ],
            )
            writer.writeheader()
            for row in trades:
                writer.writerow(
                    {
                        "timestamp": row.get("timestamp"),
                        "price": row.get("price"),
                        "size": row.get("size"),
                        "exchange": row.get("exchange"),
                        "conditions": json.dumps(row.get("conditions") or []),
                        "sequence_number": row.get("sequence_number"),
                        "tape": row.get("tape"),
                    }
                )

    return TickArchiveResult(
        report_version=TICK_ARCHIVE_VERSION,
        runtime_effect="offline_tick_archive_no_live_authority",
        symbol=symbol,
        target_date=target,
        cache_path=str(cache_path),
        trades=len(trades),
        dry_run=dry_run,
        errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Trade date, YYYY-MM-DD")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--cache-dir")
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cache_dir = Path(args.cache_dir) if args.cache_dir else ROOT / DEFAULT_TICK_ARCHIVE_DIR
    result = archive_polygon_trades(
        symbol=args.symbol,
        target_date=args.date,
        cache_dir=cache_dir,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    payload = asdict(result)
    print(json.dumps(payload, sort_keys=True))
    print(f"trades: {result.trades}")
    return 0 if result.trades and not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
