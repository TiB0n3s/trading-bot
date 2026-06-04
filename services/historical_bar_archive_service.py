"""Historical Polygon bar archiving for observe-only ML feature backfills."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from market_time import ET, is_trading_day
from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository
from services.bar_pattern_feature_service import (
    BAR_PATTERN_RUNTIME_EFFECT,
    BarPatternFeatureService,
)
from services.polygon_market_data_service import PolygonMarketDataService


HISTORICAL_BAR_ARCHIVE_VERSION = "historical_bar_archive_v1"
DEFAULT_HISTORICAL_BAR_DIR = Path("data") / "historical_bars" / "polygon_1min"


@dataclass(frozen=True)
class HistoricalBarArchiveResult:
    report_version: str
    runtime_effect: str
    symbol: str
    start_date: str
    end_date: str
    cache_path: str
    trading_days_requested: int
    trading_days_with_rows: int
    raw_bars: int
    regular_hours_bars: int
    cached_rows: int
    pattern_rows: int
    persisted_pattern_rows: int
    dry_run: bool
    errors: list[str]


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _trading_days(start_date: date, end_date: date) -> list[date]:
    days = []
    current = start_date
    while current <= end_date:
        if is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def _timestamp_et(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ET.localize(ts)
    return ts.astimezone(ET)


def _is_regular_hours_bar(bar: dict[str, Any]) -> bool:
    ts = _timestamp_et(bar.get("timestamp"))
    if ts is None:
        return False
    minutes = ts.hour * 60 + ts.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def _csv_row(symbol: str, bar: dict[str, Any]) -> dict[str, Any]:
    ts = _timestamp_et(bar.get("timestamp"))
    return {
        "Timestamp": ts.isoformat() if ts else str(bar.get("timestamp") or ""),
        "Symbol": symbol,
        "Open": bar.get("open"),
        "High": bar.get("high"),
        "Low": bar.get("low"),
        "Close": bar.get("close"),
        "Volume": bar.get("volume"),
        "VWAP": bar.get("vwap") if bar.get("vwap") is not None else bar.get("close"),
    }


class HistoricalBarArchiveService:
    def __init__(
        self,
        *,
        polygon_market_data: PolygonMarketDataService | None = None,
        bar_pattern_service: BarPatternFeatureService | None = None,
    ):
        self.polygon_market_data = polygon_market_data or PolygonMarketDataService(timeout_seconds=20.0)
        self.bar_pattern_service = bar_pattern_service

    def archive_polygon_1m_bars(
        self,
        *,
        symbol: str,
        start_date: str | date,
        end_date: str | date,
        cache_dir: Path,
        db_path: Path | str | None = None,
        build_patterns: bool = True,
        horizon_bars: int = 20,
        dry_run: bool = False,
    ) -> HistoricalBarArchiveResult:
        symbol = str(symbol or "").upper().strip()
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        if not symbol:
            raise ValueError("symbol is required")
        if end < start:
            raise ValueError("end_date must be on or after start_date")
        if not self.polygon_market_data.configured:
            raise RuntimeError("POLYGON_API_KEY is not configured")

        days = _trading_days(start, end)
        cache_dir = Path(cache_dir)
        cache_path = cache_dir / f"{symbol}_1min_rth_{start.isoformat()}_{end.isoformat()}.csv"
        raw_bars = 0
        regular_bars: list[dict[str, Any]] = []
        days_with_rows = 0
        errors: list[str] = []

        for day in days:
            try:
                bars = self.polygon_market_data.aggregate_bar_dicts(
                    symbol,
                    from_date=day.isoformat(),
                    to_date=day.isoformat(),
                    multiplier=1,
                    timespan="minute",
                    limit=50000,
                )
            except Exception as exc:
                errors.append(f"{day.isoformat()}: {type(exc).__name__}: {exc}")
                continue
            raw_bars += len(bars)
            filtered = [bar for bar in bars if _is_regular_hours_bar(bar)]
            if filtered:
                days_with_rows += 1
            regular_bars.extend(filtered)

        csv_rows = [_csv_row(symbol, bar) for bar in regular_bars]
        cached_rows = 0
        if not dry_run:
            cache_dir.mkdir(parents=True, exist_ok=True)
            with cache_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=["Timestamp", "Symbol", "Open", "High", "Low", "Close", "Volume", "VWAP"],
                )
                writer.writeheader()
                writer.writerows(csv_rows)
            cached_rows = len(csv_rows)

        pattern_rows = 0
        persisted_pattern_rows = 0
        if build_patterns and regular_bars:
            service = self.bar_pattern_service
            if service is None:
                service = BarPatternFeatureService(
                    BarPatternFeatureRepository(db_path) if db_path is not None else None
                )
            result = service.persist_features(
                regular_bars,
                symbol=symbol,
                target_date=end.isoformat(),
                timeframe="1m",
                horizon_bars=horizon_bars,
                dry_run=dry_run,
            )
            pattern_rows = result.feature_rows
            persisted_pattern_rows = result.persisted_rows

        return HistoricalBarArchiveResult(
            report_version=HISTORICAL_BAR_ARCHIVE_VERSION,
            runtime_effect=BAR_PATTERN_RUNTIME_EFFECT,
            symbol=symbol,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            cache_path=str(cache_path),
            trading_days_requested=len(days),
            trading_days_with_rows=days_with_rows,
            raw_bars=raw_bars,
            regular_hours_bars=len(regular_bars),
            cached_rows=cached_rows,
            pattern_rows=pattern_rows,
            persisted_pattern_rows=persisted_pattern_rows,
            dry_run=dry_run,
            errors=errors,
        )
