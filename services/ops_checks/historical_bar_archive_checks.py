"""Operator command for Polygon historical 1-minute bar archives."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.historical_bar_archive_service import (
    DEFAULT_HISTORICAL_BAR_DIR,
    HistoricalBarArchiveService,
)


def run_historical_bar_archive(
    start_date: str,
    *,
    base_dir: Path,
    symbol: str,
    end_date: str,
    cache_dir: Path | None = None,
    build_patterns: bool = True,
    horizon_bars: int = 20,
    dry_run: bool = False,
    polygon_market_data: Any | None = None,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Polygon Historical 1m Archive - {symbol.upper() if symbol else '-'}")
    print("=" * 72)

    if not symbol:
        print("[WARN] --symbol is required")
        return False
    if not end_date:
        print("[WARN] --end-date is required")
        return False

    db_path = base_dir / "trades.db"
    service = HistoricalBarArchiveService(polygon_market_data=polygon_market_data)
    try:
        result = service.archive_polygon_1m_bars(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            cache_dir=cache_dir or (base_dir / DEFAULT_HISTORICAL_BAR_DIR),
            db_path=db_path,
            build_patterns=build_patterns,
            horizon_bars=horizon_bars,
            dry_run=dry_run,
        )
    except Exception as exc:
        print(f"[WARN] historical bar archive failed: {type(exc).__name__}: {exc}")
        return False

    print(f"report_version          : {result.report_version}")
    print(f"runtime_effect          : {result.runtime_effect}")
    print(f"symbol                  : {result.symbol}")
    print(f"start_date              : {result.start_date}")
    print(f"end_date                : {result.end_date}")
    print(f"dry_run                 : {result.dry_run}")
    print(f"cache_path              : {result.cache_path}")
    print(f"trading_days_requested  : {result.trading_days_requested}")
    print(f"trading_days_with_rows  : {result.trading_days_with_rows}")
    print(f"raw_bars                : {result.raw_bars}")
    print(f"regular_hours_bars      : {result.regular_hours_bars}")
    print(f"cached_rows             : {result.cached_rows}")
    print(f"build_patterns          : {build_patterns}")
    print(f"pattern_rows            : {result.pattern_rows}")
    print(f"persisted_pattern_rows  : {result.persisted_pattern_rows}")

    if result.errors:
        print()
        print("Errors")
        for error in result.errors[:10]:
            print(f"  {error}")

    if not result.regular_hours_bars:
        print("[WARN] no regular-hours bars archived")
        return False

    print()
    print("[OK] historical bars archived for observe-only pattern learning")
    return True
