"""Coverage report for Polygon-derived historical bar ML features."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from repositories.historical_bar_coverage_repo import HistoricalBarCoverageRepository


HISTORICAL_BAR_COVERAGE_VERSION = "historical_bar_coverage_v1"


def _pct(numerator: int | float | None, denominator: int | float | None) -> float:
    if not denominator:
        return 0.0
    return round((float(numerator or 0) / float(denominator)) * 100.0, 2)


def _days_between(start: str | None, end: str | None) -> int:
    if not start or not end:
        return 0
    try:
        start_d = date.fromisoformat(str(start)[:10])
        end_d = date.fromisoformat(str(end)[:10])
    except ValueError:
        return 0
    return max(0, (end_d - start_d).days + 1)


def run_historical_bar_coverage(
    *,
    base_dir: Path,
    repository: HistoricalBarCoverageRepository | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    min_days: int = 252,
    min_symbols: int = 20,
) -> bool:
    print()
    print("=" * 72)
    print("  Polygon Historical Bar Coverage")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    repo = repository or HistoricalBarCoverageRepository(db_path)
    if not repo.exists():
        print(f"[WARN] missing DB: {db_path}")
        return False

    payload = repo.coverage_payload(start_date=start_date, end_date=end_date)
    if not payload or not payload.get("table_exists"):
        print("[WARN] bar_pattern_features table is missing")
        return False
    summary = payload["summary"]
    top_symbols = payload["top_symbols"]

    rows = int(summary["rows"] or 0)
    symbols = int(summary["symbols"] or 0)
    market_dates = int(summary["market_dates"] or 0)
    span_days = _days_between(summary["min_ts"], summary["max_ts"])
    training_ready = market_dates >= min_days and symbols >= min_symbols and rows > 0

    print(f"report_version          : {HISTORICAL_BAR_COVERAGE_VERSION}")
    print("runtime_effect          : readiness_only_no_live_authority")
    print(f"date_filter             : {start_date or '-'}..{end_date or '-'}")
    print(f"rows                    : {rows}")
    print(f"symbols                 : {symbols}")
    print(f"market_dates            : {market_dates}")
    print(f"calendar_span_days      : {span_days}")
    print(f"min_timestamp           : {summary['min_ts']}")
    print(f"max_timestamp           : {summary['max_ts']}")
    print(f"raw_bar_contract        : {_pct(summary['raw_contract_rows'], rows):.2f}%")
    print(f"technical_indicators    : {_pct(summary['technical_indicator_rows'], rows):.2f}%")
    print(f"triple_barrier_coverage : {_pct(summary['triple_rows'], rows):.2f}%")
    print(f"trend_scan_coverage     : {_pct(summary['trend_scan_rows'], rows):.2f}%")
    print(f"fractional_coverage     : {_pct(summary['fractional_rows'], rows):.2f}%")
    print(f"vpin_proxy_coverage     : {_pct(summary['vpin_rows'], rows):.2f}%")
    print(f"cvd_proxy_coverage      : {_pct(summary['cvd_rows'], rows):.2f}%")
    print(f"min_days_required       : {min_days}")
    print(f"min_symbols_required    : {min_symbols}")
    print(f"training_ready          : {training_ready}")

    if top_symbols:
        print()
        print("Top symbols by bar rows")
        for row in top_symbols:
            print(
                f"  {row['symbol']:<8} rows={int(row['rows'] or 0):<8} "
                f"{row['min_ts']}..{row['max_ts']}"
            )

    if training_ready:
        print()
        print("[OK] historical bar coverage meets configured ML training floor")
        return True

    print()
    print("[WARN] historical bar coverage does not yet meet configured ML training floor")
    return False
