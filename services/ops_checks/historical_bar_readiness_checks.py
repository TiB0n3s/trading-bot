"""Consolidated historical-bar ML readiness and data-quality report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repositories.historical_bar_quality_repo import HistoricalBarQualityRepository
from services.bar_pattern_feature_service import BAR_PATTERN_FEATURE_VERSION
from services.ops_checks.historical_bar_progress_checks import (
    DEFAULT_MANIFEST_DIR,
    _cache_symbol_progress,
    _load_manifests,
)
from symbols_config import APPROVED_SYMBOLS_LIST, SYMBOL_UNIVERSE_VERSION


HISTORICAL_BAR_READINESS_VERSION = "historical_bar_readiness_v1"
CURRENT_FEATURE_VERSION_ALIASES = (BAR_PATTERN_FEATURE_VERSION, "v4")
READINESS_FEATURE_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "sma_20",
    "bollinger_percent_b_20",
    "rolling_volatility_20_pct",
    "day_of_week",
    "minute_of_day",
    "ema_12",
    "ema_26",
    "macd",
    "rsi_14",
    "atr_20_pct",
    "volume_ratio_20",
    "cumulative_volume_delta",
    "vpin_toxicity_20",
    "fractional_diff_zscore_20",
    "triple_barrier_label",
    "trend_scan_label",
)


def _pct(numerator: int | float | None, denominator: int | float | None) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator or 0) / float(denominator) * 100.0, 2)


def _quality_payload(
    *,
    db_path: Path,
    start_date: str | None,
    end_date: str | None,
    include_duplicate_scan: bool = False,
    symbols: list[str] | None = None,
    symbol_limit: int = 0,
    quality_mode: str = "sample",
    sample_rows_per_symbol: int = 2000,
) -> dict[str, Any]:
    return HistoricalBarQualityRepository(db_path).quality_payload(
        readiness_feature_columns=READINESS_FEATURE_COLUMNS,
        current_feature_version_aliases=CURRENT_FEATURE_VERSION_ALIASES,
        start_date=start_date,
        end_date=end_date,
        include_duplicate_scan=include_duplicate_scan,
        symbols=symbols,
        symbol_limit=symbol_limit,
        quality_mode=quality_mode,
        sample_rows_per_symbol=sample_rows_per_symbol,
    )


def _manifest_summary(base_dir: Path) -> dict[str, Any]:
    manifests = _load_manifests(base_dir / DEFAULT_MANIFEST_DIR, limit=10)
    errors = [err for manifest in manifests for err in (manifest.get("errors") or [])]
    latest = manifests[0] if manifests else {}
    latest_errors = latest.get("errors") or []
    return {
        "recent_manifest_count": len(manifests),
        "recent_manifest_errors": len(errors),
        "latest_manifest_errors": len(latest_errors),
        "latest_manifest": latest,
        "recent_errors": errors,
        "latest_errors": latest_errors,
    }


def _readiness_score(
    *,
    symbols_ready: int,
    min_symbols: int,
    feature_ready_pct: float,
    quality_ready: bool,
) -> int:
    symbol_pct = min(100.0, _pct(symbols_ready, min_symbols))
    quality_pct = 100.0 if quality_ready else 70.0
    score = 0.45 * symbol_pct + 0.4 * feature_ready_pct + 0.15 * quality_pct
    return int(round(min(100.0, max(0.0, score))))


def run_historical_bar_readiness(
    *,
    base_dir: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    min_days: int = 252,
    min_symbols: int = 20,
    max_feature_missing_pct: float = 5.0,
    include_db_quality: bool = False,
    include_duplicate_scan: bool = False,
    quality_symbol_limit: int = 0,
    db_quality_mode: str = "sample",
    sample_rows_per_symbol: int = 2000,
    limit: int = 15,
) -> bool:
    print()
    print("=" * 72)
    print("  Historical Bar ML Readiness")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    cache_dir = base_dir / DEFAULT_MANIFEST_DIR.parent
    cache_progress = _cache_symbol_progress(
        cache_dir,
        min_days=min_days,
        start_date=start_date,
        end_date=end_date,
    )
    ready_symbols = [row for row in cache_progress if row.get("ready")]
    remaining_symbols = [row for row in cache_progress if not row.get("ready")]
    manifest = _manifest_summary(base_dir)
    if include_db_quality:
        quality = _quality_payload(
            db_path=db_path,
            start_date=start_date,
            end_date=end_date,
            include_duplicate_scan=include_duplicate_scan,
            symbols=APPROVED_SYMBOLS_LIST,
            symbol_limit=quality_symbol_limit,
            quality_mode=db_quality_mode,
            sample_rows_per_symbol=sample_rows_per_symbol,
        )
    else:
        quality = {"table_exists": False, "reason": "db_quality_scan_skipped"}

    total_rows: int | None = None
    null_ohlcv: int | None = None
    invalid_price: int | None = None
    zero_volume: int | None = None
    duplicate_rows: int | None = None
    feature_nulls: list[dict[str, Any]] = []
    if quality.get("table_exists"):
        summary = quality.get("summary") or {}
        total_rows = int(summary.get("rows") or 0)
        null_ohlcv = int(summary.get("null_ohlcv_rows") or 0)
        invalid_price = int(summary.get("invalid_price_rows") or 0)
        zero_volume = int(summary.get("zero_volume_rows") or 0)
        duplicate_rows = quality.get("duplicate_rows")
        if duplicate_rows is not None:
            duplicate_rows = int(duplicate_rows)
        feature_nulls = list(quality.get("feature_nulls") or [])

    feature_ready = [
        row
        for row in feature_nulls
        if row.get("present") and float(row.get("missing_pct") or 0.0) <= max_feature_missing_pct
    ]
    feature_ready_pct = (
        _pct(len(feature_ready), len(feature_nulls))
        if feature_nulls
        else 100.0
    )
    quality_ready = (not include_db_quality) or (
        (total_rows or 0) > 0
        and (null_ohlcv or 0) == 0
        and (invalid_price or 0) == 0
        and (duplicate_rows is None or duplicate_rows == 0)
    )
    hook_ready = (
        len(ready_symbols) >= min_symbols
        and quality_ready
        and feature_ready_pct >= 80.0
        and int(manifest.get("latest_manifest_errors") or 0) == 0
    )
    score = _readiness_score(
        symbols_ready=len(ready_symbols),
        min_symbols=min_symbols,
        feature_ready_pct=feature_ready_pct,
        quality_ready=quality_ready,
    )

    print(f"report_version             : {HISTORICAL_BAR_READINESS_VERSION}")
    print("runtime_effect             : readiness_only_no_live_authority")
    print(f"symbol_universe_version    : {SYMBOL_UNIVERSE_VERSION}")
    print(f"date_filter                : {start_date or '-'}..{end_date or '-'}")
    print(f"symbols_expected           : {len(APPROVED_SYMBOLS_LIST)}")
    print(f"symbols_ready              : {len(ready_symbols)}")
    print(f"symbols_remaining          : {len(remaining_symbols)}")
    print(f"min_days_required          : {min_days}")
    print(f"min_symbols_required       : {min_symbols}")
    print(f"db_rows                    : {total_rows if total_rows is not None else 'not_scanned'}")
    print(f"db_quality_scan            : {'included' if include_db_quality else 'skipped'}")
    print(f"null_ohlcv_rows            : {null_ohlcv if null_ohlcv is not None else 'not_scanned'}")
    print(f"invalid_price_rows         : {invalid_price if invalid_price is not None else 'not_scanned'}")
    print(f"zero_volume_rows           : {zero_volume if zero_volume is not None else 'not_scanned'}")
    print(f"duplicate_scan             : {quality.get('duplicate_scan', 'skipped')}")
    print(f"duplicate_rows             : {duplicate_rows if duplicate_rows is not None else 'not_scanned'}")
    print(f"feature_ready_pct          : {feature_ready_pct:.2f}%")
    print(f"quality_ready              : {quality_ready}")
    print(f"readiness_score_pct        : {score}/100")
    print(f"completion_hook_ready      : {hook_ready}")
    print(f"recent_manifest_count      : {manifest['recent_manifest_count']}")
    print(f"recent_manifest_errors     : {manifest['recent_manifest_errors']}")
    print(f"latest_manifest_errors     : {manifest['latest_manifest_errors']}")
    if include_db_quality:
        print(f"db_quality_mode           : {quality.get('quality_mode', 'unknown')}")
        if quality.get("sample_rows_per_symbol"):
            print(f"sample_rows_per_symbol    : {quality.get('sample_rows_per_symbol')}")
        print(f"quality_symbols_scanned    : {len(quality.get('symbols_scanned') or [])}")
        print(f"quality_symbol_limited     : {quality.get('symbol_scan_limited', False)}")

    latest = manifest.get("latest_manifest") or {}
    if latest:
        print()
        print("Latest backfill manifest")
        print(f"  file                     : {latest.get('manifest_file')}")
        print(f"  attempted_chunks         : {latest.get('attempted_chunks')}")
        print(f"  successful_chunks        : {latest.get('successful_chunks')}")
        print(f"  skipped_chunks           : {latest.get('skipped_chunks')}")
        print(f"  cached_rows              : {latest.get('cached_rows')}")
        print(f"  persisted_rows           : {latest.get('persisted_pattern_rows')}")

    recent_errors = manifest.get("recent_errors") or []
    if recent_errors:
        print()
        if int(manifest.get("latest_manifest_errors") or 0) == 0:
            print("Recent manifest errors (historical; latest manifest is clean)")
        else:
            print("Recent manifest errors")
        for err in recent_errors[:limit]:
            print(f"  {err}")

    if include_db_quality and quality.get("table_exists"):
        summary = quality.get("summary") or {}
        print()
        print("Training label coverage")
        print(f"  triple_barrier_rows      : {summary.get('triple_rows')}")
        print(f"  trend_scan_rows          : {summary.get('trend_scan_rows')}")
        print(f"  fractional_rows          : {summary.get('fractional_rows')}")
        print(f"  vpin_rows                : {summary.get('vpin_rows')}")
        print(f"  cvd_rows                 : {summary.get('cvd_rows')}")

    if feature_nulls:
        print()
        print("Feature missing-rate watchlist")
        risky = sorted(
            feature_nulls,
            key=lambda row: (
                row.get("present") is True,
                -float(row.get("missing_pct") or 0.0),
                str(row.get("feature")),
            ),
        )
        for row in risky[:limit]:
            present = "yes" if row.get("present") else "no"
            print(
                f"  {str(row.get('feature')):<32} present={present:<3} "
                f"missing={float(row.get('missing_pct') or 0.0):>6.2f}%"
            )

    incomplete = sorted(
        remaining_symbols,
        key=lambda row: (int(row.get("market_dates") or 0), str(row.get("symbol"))),
    )
    if incomplete:
        print()
        print("Next symbols needing backfill")
        for row in incomplete[:limit]:
            print(
                f"  {row['symbol']:<8} dates={int(row.get('market_dates') or 0):<4} "
                f"remaining_days={int(row.get('days_remaining') or 0):<4} "
                f"chunks={int(row.get('cache_chunks') or 0):<4}"
            )

    print()
    if hook_ready:
        print("[OK] historical bars are ready for observe-only training hook")
        print(
            "next_command              : "
            "python3 pipeline/retrain.py --force --rerun-completed --date "
            f"{end_date or 'YYYY-MM-DD'}"
        )
        return True

    print("[WARN] historical bars are not yet ready for automated training completion hook")
    return False
