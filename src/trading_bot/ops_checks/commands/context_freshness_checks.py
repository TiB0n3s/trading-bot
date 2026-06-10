"""Freshness checks for runtime context inputs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.ops_check_repo import OpsCheckRepository

DEFAULT_STALE_MINUTES = {
    "market_context_file": 24 * 60,
    "intraday_refresh": 90,
    "daily_symbol_context": 24 * 60,
    "daily_symbol_events": 24 * 60,
    "daily_symbol_predictions": 24 * 60,
    "feature_snapshots": 30,
    "session_momentum": 15,
}
CONTEXT_FRESHNESS_REPORT_VERSION = "context_freshness_v1"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _age_minutes(value: Any, *, now: datetime) -> float | None:
    dt = _parse_dt(value)
    if not dt:
        return None
    return max(0.0, (now - dt).total_seconds() / 60.0)


def _status(age: float | None, threshold: int, *, present: bool = True) -> str:
    if not present:
        return "missing"
    if age is None:
        return "unknown"
    return "stale" if age > threshold else "fresh"


def _print_row(
    name: str, latest_at: Any, rows: int | None, threshold: int, *, now: datetime
) -> bool:
    age = _age_minutes(latest_at, now=now)
    status = _status(age, threshold, present=latest_at is not None)
    age_s = "-" if age is None else f"{age:.1f}m"
    rows_s = "-" if rows is None else str(rows)
    print(
        f"  {name:<28} status={status:<8} age={age_s:>8} rows={rows_s:>6} latest={latest_at or '-'}"
    )
    return status in {"fresh", "unknown"} and (rows is None or rows > 0)


def run_context_freshness(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"
    repo = OpsCheckRepository(db_path)
    now = datetime.now(timezone.utc)

    print()
    print("=" * 72)
    print(f"  Context Freshness - {target_date}")
    print("=" * 72)
    print(f"report_version          : {CONTEXT_FRESHNESS_REPORT_VERSION}")

    ok = True

    market_context_path = base_dir / "market_context.json"
    market_context = {}
    if market_context_path.exists():
        try:
            market_context = json.loads(market_context_path.read_text())
        except Exception as e:
            print(f"[WARN] could not parse market_context.json: {e}")
            ok = False
    else:
        print("[WARN] market_context.json missing")
        ok = False

    print("File/context artifacts")
    if market_context_path.exists():
        mtime = datetime.fromtimestamp(
            market_context_path.stat().st_mtime, timezone.utc
        ).isoformat()
        ok = (
            _print_row(
                "market_context_file",
                mtime,
                1,
                DEFAULT_STALE_MINUTES["market_context_file"],
                now=now,
            )
            and ok
        )
    intraday_at = market_context.get("intraday_refresh_at")
    if intraday_at:
        ok = (
            _print_row(
                "intraday_refresh",
                intraday_at,
                1,
                DEFAULT_STALE_MINUTES["intraday_refresh"],
                now=now,
            )
            and ok
        )
    else:
        print("  intraday_refresh             status=missing  age=       - rows=     - latest=-")

    if not repo.exists():
        print()
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    freshness = repo.context_freshness_row(target_date)

    print()
    print("Database context inputs")
    checks = [
        (
            "daily_symbol_context",
            freshness["daily_symbol_context_latest_at"],
            freshness["daily_symbol_context_rows"],
            DEFAULT_STALE_MINUTES["daily_symbol_context"],
        ),
        (
            "daily_symbol_events",
            freshness["daily_symbol_events_latest_at"],
            freshness["daily_symbol_events_rows"],
            DEFAULT_STALE_MINUTES["daily_symbol_events"],
        ),
        (
            "daily_symbol_predictions",
            freshness["daily_symbol_predictions_latest_at"],
            freshness["daily_symbol_predictions_rows"],
            DEFAULT_STALE_MINUTES["daily_symbol_predictions"],
        ),
        (
            "feature_snapshots",
            freshness["feature_snapshots_latest_at"],
            freshness["feature_snapshots_rows"],
            DEFAULT_STALE_MINUTES["feature_snapshots"],
        ),
        (
            "session_momentum",
            freshness["session_momentum_latest_at"],
            freshness["session_momentum_rows"],
            DEFAULT_STALE_MINUTES["session_momentum"],
        ),
    ]
    for name, latest_at, rows, threshold in checks:
        ok = _print_row(name, latest_at, rows, threshold, now=now) and ok

    print()
    print(
        "[OK] context freshness looks usable"
        if ok
        else "[WARN] context freshness has stale or missing inputs"
    )
    return ok


def run_data_freshness_gate(target_date: str, *, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print(f"  Data Freshness Gate - {target_date}")
    print("=" * 72)
    print("report_version          : data_freshness_gate_v1")
    print(
        "gate_scope              : market_context,event_context,predictions,setup_snapshots,session_momentum,rolling_momentum,labels"
    )
    return run_context_freshness(target_date, base_dir=base_dir)
