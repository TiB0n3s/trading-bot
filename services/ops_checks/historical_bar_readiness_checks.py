"""Consolidated historical-bar ML readiness and data-quality report."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from repositories.historical_bar_coverage_repo import HistoricalBarCoverageRepository
from services.ops_checks.historical_bar_progress_checks import (
    DEFAULT_MANIFEST_DIR,
    _cache_symbol_progress,
    _load_manifests,
)
from symbols_config import APPROVED_SYMBOLS_LIST, SYMBOL_UNIVERSE_VERSION


HISTORICAL_BAR_READINESS_VERSION = "historical_bar_readiness_v1"
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


def _connect_ro(db_path: Path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in con.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _count_expr(columns: set[str], condition: str, alias: str) -> str:
    return f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) AS {alias}"


def _quality_payload(
    *,
    db_path: Path,
    start_date: str | None,
    end_date: str | None,
    include_duplicate_scan: bool = False,
) -> dict[str, Any]:
    if not db_path.exists():
        return {"table_exists": False, "reason": "missing_db"}
    with _connect_ro(db_path) as con:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bar_pattern_features'"
        ).fetchone()
        if not exists:
            return {"table_exists": False, "reason": "missing_bar_pattern_features"}
        columns = _table_columns(con, "bar_pattern_features")

        where = ["1=1"]
        params: list[Any] = []
        if "timeframe" in columns:
            where.append("timeframe = '1m'")
        if start_date:
            where.append("substr(bar_timestamp, 1, 10) >= ?")
            params.append(start_date)
        if end_date:
            where.append("substr(bar_timestamp, 1, 10) <= ?")
            params.append(end_date)
        where_sql = " AND ".join(where)

        required_price_cols = {"open", "high", "low", "close", "volume"}
        if required_price_cols <= columns:
            null_contract_expr = _count_expr(
                columns,
                "open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume IS NULL",
                "null_ohlcv_rows",
            )
            invalid_price_expr = _count_expr(
                columns,
                "high < low OR open < low OR open > high OR close < low OR close > high",
                "invalid_price_rows",
            )
            zero_volume_expr = _count_expr(columns, "volume <= 0", "zero_volume_rows")
        else:
            null_contract_expr = "0 AS null_ohlcv_rows"
            invalid_price_expr = "0 AS invalid_price_rows"
            zero_volume_expr = "0 AS zero_volume_rows"

        summary = con.execute(
            f"""
            SELECT
                COUNT(*) AS rows,
                COUNT(DISTINCT symbol) AS symbols,
                COUNT(DISTINCT substr(bar_timestamp, 1, 10)) AS market_dates,
                MIN(substr(bar_timestamp, 1, 10)) AS first_date,
                MAX(substr(bar_timestamp, 1, 10)) AS last_date,
                {null_contract_expr},
                {invalid_price_expr},
                {zero_volume_expr}
            FROM bar_pattern_features
            WHERE {where_sql}
            """,
            params,
        ).fetchone()
        timeframe_group = "timeframe" if "timeframe" in columns else "'1m'"
        feature_version_group = "feature_version" if "feature_version" in columns else "''"

        duplicate_rows: int | None = None
        if include_duplicate_scan:
            duplicates = con.execute(
                f"""
                SELECT COALESCE(SUM(extra_rows), 0) AS duplicate_rows
                FROM (
                    SELECT COUNT(*) - 1 AS extra_rows
                    FROM bar_pattern_features
                    WHERE {where_sql}
                    GROUP BY symbol, bar_timestamp, {timeframe_group}, {feature_version_group}
                    HAVING COUNT(*) > 1
                )
                """,
                params,
            ).fetchone()
            duplicate_rows = int(duplicates["duplicate_rows"] or 0)

        feature_nulls: list[dict[str, Any]] = []
        total_rows = int(summary["rows"] or 0)
        present_columns = [column for column in READINESS_FEATURE_COLUMNS if column in columns]
        missing_exprs = [
            f"SUM(CASE WHEN {column} IS NULL THEN 1 ELSE 0 END) AS missing_{idx}"
            for idx, column in enumerate(present_columns)
        ]
        missing_row = None
        if missing_exprs:
            missing_row = con.execute(
                f"""
                SELECT {', '.join(missing_exprs)}
                FROM bar_pattern_features
                WHERE {where_sql}
                """,
                params,
            ).fetchone()

        for idx, column in enumerate(READINESS_FEATURE_COLUMNS):
            if column not in columns:
                feature_nulls.append(
                    {
                        "feature": column,
                        "present": False,
                        "missing_rows": total_rows,
                        "missing_pct": 100.0 if total_rows else 0.0,
                    }
                )
                continue
            present_idx = present_columns.index(column)
            missing = int((missing_row or {})[f"missing_{present_idx}"] or 0)
            feature_nulls.append(
                {
                    "feature": column,
                    "present": True,
                    "missing_rows": missing,
                    "missing_pct": _pct(missing, total_rows),
                }
            )

    return {
        "table_exists": True,
        "summary": dict(summary),
        "duplicate_rows": duplicate_rows,
        "duplicate_scan": "included" if include_duplicate_scan else "skipped",
        "feature_nulls": feature_nulls,
    }


def _manifest_summary(base_dir: Path) -> dict[str, Any]:
    manifests = _load_manifests(base_dir / DEFAULT_MANIFEST_DIR, limit=10)
    errors = [err for manifest in manifests for err in (manifest.get("errors") or [])]
    latest = manifests[0] if manifests else {}
    return {
        "recent_manifest_count": len(manifests),
        "recent_manifest_errors": len(errors),
        "latest_manifest": latest,
        "recent_errors": errors,
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
        )
        coverage_repo = HistoricalBarCoverageRepository(db_path)
        coverage = coverage_repo.coverage_payload(start_date=start_date, end_date=end_date) if db_path.exists() else None
    else:
        quality = {"table_exists": False, "reason": "db_quality_scan_skipped"}
        coverage = None

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
    feature_ready_pct = _pct(len(feature_ready), len(feature_nulls))
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
        and int(manifest.get("recent_manifest_errors") or 0) == 0
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
        print("Recent manifest errors")
        for err in recent_errors[:limit]:
            print(f"  {err}")

    if coverage and coverage.get("table_exists"):
        summary = coverage.get("summary") or {}
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
