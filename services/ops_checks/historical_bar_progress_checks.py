"""Progress monitor for multi-symbol Polygon historical bar backfills."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from repositories.historical_bar_coverage_repo import HistoricalBarCoverageRepository
from symbols_config import APPROVED_SYMBOLS_LIST, SYMBOL_UNIVERSE_VERSION


HISTORICAL_BAR_PROGRESS_VERSION = "historical_bar_progress_v1"
DEFAULT_MANIFEST_DIR = (
    Path("data")
    / "historical_bars"
    / "polygon_1min"
    / "backfill_manifests"
)


def _load_manifests(manifest_dir: Path, limit: int = 5) -> list[dict[str, Any]]:
    if not manifest_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(manifest_dir.glob("historical_bar_backfill_*.json"), reverse=True)[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            payload = {"errors": [f"manifest_read_failed:{type(exc).__name__}:{exc}"]}
        payload["manifest_file"] = path.name
        rows.append(payload)
    return rows


def _symbol_progress(
    symbol_rows: list[dict[str, Any]],
    *,
    min_days: int,
) -> list[dict[str, Any]]:
    by_symbol = {str(row["symbol"]): row for row in symbol_rows}
    progress: list[dict[str, Any]] = []
    for symbol in APPROVED_SYMBOLS_LIST:
        row = by_symbol.get(symbol) or {}
        market_dates = int(row.get("market_dates") or 0)
        rows = int(row.get("rows") or 0)
        progress.append(
            {
                "symbol": symbol,
                "rows": rows,
                "market_dates": market_dates,
                "days_remaining": max(0, min_days - market_dates),
                "ready": market_dates >= min_days,
                "triple_barrier_rows": int(row.get("triple_rows") or 0),
                "trend_scan_rows": int(row.get("trend_scan_rows") or 0),
            }
        )
    return progress


def _weekdays_between(start: str, end: str) -> int:
    try:
        current = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError:
        return 0
    days = 0
    while current <= end_date:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def _cache_file_has_rows(path: Path) -> bool:
    """Return True when a cached CSV has at least one data row.

    Header-only files should not contribute coverage. They can be produced by
    interrupted or failed provider fetches and otherwise create false readiness.
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            next(fh, None)
            return next(fh, None) is not None
    except Exception:
        return False


def _cache_symbol_progress(
    cache_dir: Path,
    *,
    min_days: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    if not cache_dir.is_dir():
        return []
    by_symbol: dict[str, dict[str, Any]] = {
        symbol: {
            "symbol": symbol,
            "rows": 0,
            "market_dates": 0,
            "days_remaining": min_days,
            "ready": False,
            "triple_barrier_rows": 0,
            "trend_scan_rows": 0,
            "cache_chunks": 0,
            "empty_cache_chunks": 0,
            "coverage_source": "cache_chunk_estimate",
        }
        for symbol in APPROVED_SYMBOLS_LIST
    }
    for path in cache_dir.glob("*_1min_rth_????-??-??_????-??-??.csv"):
        stem = path.stem
        marker = "_1min_rth_"
        if marker not in stem:
            continue
        symbol, date_part = stem.split(marker, 1)
        if symbol not in by_symbol:
            continue
        parts = date_part.split("_")
        if len(parts) != 2:
            continue
        start, end = parts
        if start_date and end < start_date:
            continue
        if end_date and start > end_date:
            continue
        if start_date and start < start_date:
            start = start_date
        if end_date and end > end_date:
            end = end_date
        rec = by_symbol[symbol]
        rec["cache_chunks"] += 1
        if not _cache_file_has_rows(path):
            rec["empty_cache_chunks"] += 1
            continue
        rec["market_dates"] += _weekdays_between(start, end)
    for rec in by_symbol.values():
        rec["days_remaining"] = max(0, min_days - int(rec["market_dates"] or 0))
        rec["ready"] = int(rec["market_dates"] or 0) >= min_days
    return list(by_symbol.values())


def run_historical_bar_progress(
    *,
    base_dir: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    min_days: int = 252,
    min_symbols: int = 20,
    limit: int = 15,
    repository: HistoricalBarCoverageRepository | None = None,
) -> bool:
    print()
    print("=" * 72)
    print("  Polygon Historical Bar Backfill Progress")
    print("=" * 72)

    cache_dir = base_dir / DEFAULT_MANIFEST_DIR.parent
    cache_progress = _cache_symbol_progress(
        cache_dir,
        min_days=min_days,
        start_date=start_date,
        end_date=end_date,
    )
    if cache_progress:
        symbol_progress = cache_progress
        progress_source = "cache_chunk_estimate"
    else:
        db_path = base_dir / "trades.db"
        repo = repository or HistoricalBarCoverageRepository(db_path)
        if not repo.exists():
            print(f"[WARN] missing DB: {db_path}")
            return False

        payload = repo.symbol_progress_payload(
            start_date=start_date,
            end_date=end_date,
            symbols=APPROVED_SYMBOLS_LIST,
        )
        if not payload or not payload.get("table_exists"):
            print("[WARN] bar_pattern_features table is missing")
            return False
        symbol_progress = _symbol_progress(
            payload.get("symbol_rows") or [],
            min_days=min_days,
        )
        progress_source = "database_symbol_counts"

    ready_symbols = [row for row in symbol_progress if row["ready"]]
    incomplete = [row for row in symbol_progress if not row["ready"]]
    priority = sorted(
        incomplete,
        key=lambda row: (row["market_dates"], -row["rows"], row["symbol"]),
    )
    manifests = _load_manifests(base_dir / DEFAULT_MANIFEST_DIR)
    recent_errors = [
        err
        for manifest in manifests
        for err in (manifest.get("errors") or [])
    ]

    print(f"report_version          : {HISTORICAL_BAR_PROGRESS_VERSION}")
    print("runtime_effect          : readiness_only_no_live_authority")
    print(f"symbol_universe_version : {SYMBOL_UNIVERSE_VERSION}")
    print(f"date_filter             : {start_date or '-'}..{end_date or '-'}")
    print(f"progress_source         : {progress_source}")
    print(f"symbols_expected        : {len(APPROVED_SYMBOLS_LIST)}")
    print(f"symbols_ready           : {len(ready_symbols)}")
    print(f"symbols_remaining       : {len(incomplete)}")
    print(f"min_days_required       : {min_days}")
    print(f"min_symbols_required    : {min_symbols}")
    print(f"cache_floor_ready       : {len(ready_symbols) >= min_symbols}")
    print(f"recent_manifest_count   : {len(manifests)}")
    print(f"recent_manifest_errors  : {len(recent_errors)}")

    if manifests:
        latest = manifests[0]
        print()
        print("Latest manifest")
        print(f"  file                  : {latest.get('manifest_file')}")
        print(f"  attempted_chunks      : {latest.get('attempted_chunks')}")
        print(f"  successful_chunks     : {latest.get('successful_chunks')}")
        print(f"  skipped_chunks        : {latest.get('skipped_chunks')}")
        print(f"  cached_rows           : {latest.get('cached_rows')}")
        print(f"  persisted_rows        : {latest.get('persisted_pattern_rows')}")
        print(f"  errors                : {len(latest.get('errors') or [])}")

    print()
    print("Priority symbols below day floor")
    if priority:
        for row in priority[:limit]:
            print(
                f"  {row['symbol']:<8} dates={row['market_dates']:<4} "
                f"rows={row['rows']:<8} remaining_days={row['days_remaining']:<4} "
                f"chunks={row.get('cache_chunks', '-'):<4} "
                f"empty={row.get('empty_cache_chunks', 0):<4} "
                f"triple={row['triple_barrier_rows']:<8} trend={row['trend_scan_rows']:<8}"
            )
    else:
        print("  none")

    if recent_errors:
        print()
        print("Recent manifest errors")
        for err in recent_errors[:limit]:
            print(f"  {err}")

    if len(ready_symbols) >= min_symbols and not recent_errors:
        print()
        print("[OK] cached backfill progress meets configured symbol/day floor")
        return True

    print()
    if recent_errors:
        print("[WARN] recent backfill manifests contain errors")
    if len(ready_symbols) < min_symbols:
        print("[WARN] too few cached symbols meet the configured historical day floor")
    return False
