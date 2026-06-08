"""Operator check for live bar-pattern feature capture freshness."""

from __future__ import annotations

from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository


LIVE_BAR_PATTERN_CAPTURE_REPORT_VERSION = "live_bar_pattern_capture_v1"


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _market_session_active(target_date: str) -> bool:
    now = datetime.now(ZoneInfo("America/Chicago"))
    if now.date().isoformat() != target_date or now.weekday() >= 5:
        return False
    return time(8, 30) <= now.time() <= time(15, 10)


def _age_minutes(value: object) -> float | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds() / 60.0


def run_live_bar_pattern_capture_report(
    target_date: str,
    *,
    base_dir: Path,
    max_age_minutes: int = 5,
    min_symbols: int = 1,
    timeframe: str = "1m",
    limit: int = 12,
) -> bool:
    repo = BarPatternFeatureRepository(base_dir / "trades.db")
    summary = repo.live_capture_summary(
        target_date=target_date,
        timeframe=timeframe,
        limit=limit,
    )
    latest_age = _age_minutes(summary.get("latest_created_at") or summary.get("latest_bar_timestamp"))
    session_active = _market_session_active(target_date)
    rows = int(summary.get("rows") or 0)
    symbols = int(summary.get("symbols") or 0)
    latest_fresh = latest_age is not None and latest_age <= max(1, max_age_minutes)
    coverage_ok = rows > 0 and symbols >= max(1, min_symbols)
    active_capture_ok = coverage_ok and (latest_fresh if session_active else True)

    print()
    print("=" * 72)
    print("  Live Bar-Pattern Feature Capture")
    print("=" * 72)
    print(f"report_version          : {LIVE_BAR_PATTERN_CAPTURE_REPORT_VERSION}")
    print("runtime_effect          : verification_only_no_live_authority")
    print(f"target_date             : {target_date}")
    print(f"timeframe               : {timeframe}")
    print(f"session_active_now      : {session_active}")
    print(f"max_age_minutes         : {max_age_minutes}")

    if not summary.get("table_exists"):
        print("table_exists            : False")
        print("[FAIL] bar_pattern_features table is missing")
        return False

    print(f"rows_today              : {rows}")
    print(f"symbols_today           : {symbols}")
    print(f"min_symbols             : {min_symbols}")
    print(f"first_bar_timestamp     : {summary.get('first_bar_timestamp') or '-'}")
    print(f"latest_bar_timestamp    : {summary.get('latest_bar_timestamp') or '-'}")
    print(f"latest_created_at       : {summary.get('latest_created_at') or '-'}")
    if latest_age is None:
        print("latest_capture_age_min  : unknown")
    else:
        print(f"latest_capture_age_min  : {latest_age:.2f}")
    print(f"coverage_ok             : {coverage_ok}")
    print(f"freshness_ok            : {latest_fresh if session_active else 'not_required_outside_active_session'}")

    print()
    print("Sources")
    if summary.get("sources"):
        for row in summary["sources"]:
            print(f"  {row['source']:<36} rows={row['rows']}")
    else:
        print("  none")

    print()
    print("Feature versions")
    for row in summary.get("feature_versions") or []:
        print(f"  {row['feature_version']:<36} rows={row['rows']}")
    if not summary.get("feature_versions"):
        print("  none")

    print()
    print("Latest rows by symbol")
    latest_rows = summary.get("latest_rows") or []
    if latest_rows:
        for row in latest_rows:
            print(
                f"  {row.get('symbol', '-'):<6} {row.get('bar_timestamp') or '-'} "
                f"src={row.get('bar_source') or '-'} feed={row.get('bar_feed') or '-'} "
                f"close={row.get('close')} vpin={row.get('vpin_toxicity_20')} "
                f"trend={row.get('trend_scan_label')} triple={row.get('triple_barrier_label')}"
            )
    else:
        print("  none")

    print()
    print("Expected capture path")
    print("  cron: job_runner session_momentum every 2 minutes during market hours")
    print("  service: SessionMomentumService.refresh_from_bars -> BarPatternFeatureService.persist_features")
    print("  env: SESSION_MOMENTUM_CAPTURE_BAR_PATTERNS defaults to true")

    print()
    if active_capture_ok:
        print("[OK] live bar-pattern capture evidence is available")
        return True
    if session_active:
        print("[FAIL] live bar-pattern capture is stale or missing during active session")
    else:
        print("[WARN] no target-date bar-pattern capture evidence yet")
    return False
