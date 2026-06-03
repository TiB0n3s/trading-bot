"""Operator backfill/report for EFI/PVT bar-pattern features."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository
from services.bar_pattern_feature_service import BarPatternFeatureService
from services.polygon_market_data_service import PolygonMarketDataService


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def run_bar_pattern_backfill(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str,
    dry_run: bool = False,
    timeframe_minutes: int = 5,
    horizon_bars: int = 12,
    polygon_market_data: Any | None = None,
) -> bool:
    symbol = str(symbol or "").upper().strip()
    print()
    print("=" * 72)
    print(f"  EFI/PVT Bar Pattern Backfill - {target_date}")
    print("=" * 72)

    if not symbol:
        print("[WARN] --symbol is required")
        return False

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    polygon = polygon_market_data or PolygonMarketDataService(timeout_seconds=15.0)
    if not polygon.configured:
        print("[WARN] POLYGON_API_KEY is not configured")
        return False

    service = BarPatternFeatureService(BarPatternFeatureRepository(db_path))
    try:
        bars = polygon.aggregate_bar_dicts(
            symbol,
            from_date=target_date,
            to_date=target_date,
            multiplier=timeframe_minutes,
            timespan="minute",
        )
        result = service.persist_features(
            bars,
            symbol=symbol,
            target_date=target_date,
            timeframe=f"{timeframe_minutes}m",
            horizon_bars=horizon_bars,
            dry_run=dry_run,
        )
    except Exception as exc:
        print(f"[WARN] bar-pattern backfill failed: {type(exc).__name__}: {exc}")
        return False

    print(f"report_version       : {result.report_version}")
    print(f"runtime_effect       : {result.runtime_effect}")
    print(f"symbol               : {result.symbol}")
    print(f"date                 : {result.date}")
    print(f"timeframe            : {result.timeframe}")
    print(f"horizon_bars         : {horizon_bars}")
    print(f"dry_run              : {dry_run}")
    print(f"bars                 : {result.bars}")
    print(f"feature_rows         : {result.feature_rows}")
    print(f"persisted_rows       : {result.persisted_rows}")

    if dry_run:
        summary = {
            "rows": result.feature_rows,
            "symbols": 1 if result.feature_rows else 0,
            "rows_with_forward_outcome": result.rows_with_forward_outcome,
            "labels": result.label_summary,
            "opportunities": result.opportunity_summary,
        }
    else:
        summary = service.summary(target_date, symbol=symbol)
    print()
    print("Pattern summary")
    print(f"  rows                         : {summary['rows']}")
    print(f"  symbols                      : {summary['symbols']}")
    print(f"  rows_with_forward_outcome    : {summary['rows_with_forward_outcome']}")
    if summary["labels"]:
        print()
        print(f"  {'pattern':<32} {'rows':>6} {'ret':>9} {'mfe':>9} {'mae':>9}")
        print(f"  {'-' * 32} {'-' * 6} {'-' * 9} {'-' * 9} {'-' * 9}")
        for row in summary["labels"][:12]:
            print(
                f"  {str(row.get('pattern_label') or 'unknown'):<32} "
                f"{int(row.get('rows') or 0):>6} "
                f"{_fmt(row.get('avg_forward_return_pct')):>9} "
                f"{_fmt(row.get('avg_forward_mfe_pct')):>9} "
                f"{_fmt(row.get('avg_forward_mae_pct')):>9}"
            )

    if summary.get("opportunities"):
        print()
        print("Hindsight opportunity summary")
        print(f"  {'action':<24} {'quality':<32} {'rows':>6} {'long':>8} {'sell':>8} {'ret':>8}")
        print(f"  {'-' * 24} {'-' * 32} {'-' * 6} {'-' * 8} {'-' * 8} {'-' * 8}")
        for row in summary["opportunities"][:12]:
            print(
                f"  {str(row.get('opportunity_action') or 'unknown'):<24} "
                f"{str(row.get('opportunity_quality') or 'unknown'):<32} "
                f"{int(row.get('rows') or 0):>6} "
                f"{_fmt(row.get('avg_long_opportunity_score'), 2):>8} "
                f"{_fmt(row.get('avg_sell_opportunity_score'), 2):>8} "
                f"{_fmt(row.get('avg_forward_return_pct')):>8}"
            )

    if not result.feature_rows:
        print("[WARN] no feature rows built; need at least 21 bars")
        return False

    print()
    print("[OK] EFI/PVT pattern rows captured; no live authority changed")
    return True
