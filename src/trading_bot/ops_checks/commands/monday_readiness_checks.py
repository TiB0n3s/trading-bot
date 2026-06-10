"""Weekend-to-Monday readiness checklist for the trading platform."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.historical_bar_training_repo import fetch_historical_bar_training_rows
from symbols_config import APPROVED_SYMBOLS_LIST

from trading_bot.ops_checks.commands.historical_bar_model_checks import (
    DEFAULT_CANDIDATE_DIR,
    _assess,
    _diagnostics,
    _latest_by_label,
)
from trading_bot.ops_checks.commands.historical_bar_progress_checks import (
    DEFAULT_MANIFEST_DIR,
    _cache_symbol_progress,
)

MONDAY_READINESS_VERSION = "monday_readiness_check_v1"


def _file_age_hours(path: Path) -> float | None:
    if not path.exists():
        return None
    return round((datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600.0, 2)


def _env_has_key(env_path: Path, key: str) -> bool:
    if not env_path.exists():
        return False
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}=") and line.split("=", 1)[1].strip():
                return True
    except Exception:
        return False
    return False


def _historical_bar_symbol_count(base_dir: Path) -> int:
    rows = fetch_historical_bar_training_rows(
        db_path=base_dir / "trades.db",
        start_date="2024-06-01",
        end_date=datetime.now(timezone.utc).date().isoformat(),
        rows_per_symbol=1,
        limit=len(APPROVED_SYMBOLS_LIST) + 5,
    )
    return len({str(row.get("symbol")) for row in rows if row.get("symbol")})


def _model_candidate_status() -> dict[str, Any]:
    diagnostics = _diagnostics(DEFAULT_CANDIDATE_DIR)
    latest = _latest_by_label(diagnostics)
    assessments = {
        label: _assess(row, min_rows=5000, min_symbols=59, min_accuracy=0.50)
        for label, row in latest.items()
    }
    return {
        "diagnostics": len(diagnostics),
        "labels": sorted(assessments),
        "ready_labels": sorted(
            label
            for label, item in assessments.items()
            if item.status == "observe_only_candidate_ready"
        ),
        "failed": {
            label: item.failed_thresholds
            for label, item in assessments.items()
            if item.failed_thresholds
        },
    }


def run_monday_readiness_check(
    *,
    base_dir: Path,
    min_historical_symbols: int = 59,
) -> bool:
    checks: list[dict[str, Any]] = []

    trades_db = base_dir / "trades.db"
    checks.append(
        {
            "name": "trades_db_exists",
            "ok": trades_db.exists(),
            "required": True,
            "detail": str(trades_db),
        }
    )

    market_context = base_dir / "market_context.json"
    checks.append(
        {
            "name": "market_context_exists",
            "ok": market_context.exists(),
            "required": True,
            "detail": f"age_hours={_file_age_hours(market_context)}",
        }
    )

    env_path = Path("/etc/trading-bot.env")
    checks.append(
        {
            "name": "polygon_key_configured",
            "ok": _env_has_key(env_path, "POLYGON_API_KEY"),
            "required": True,
            "detail": str(env_path),
        }
    )

    historical_symbols = _historical_bar_symbol_count(base_dir)
    checks.append(
        {
            "name": "historical_bar_symbol_coverage",
            "ok": historical_symbols >= min_historical_symbols,
            "required": True,
            "detail": f"{historical_symbols}/{min_historical_symbols}",
        }
    )

    full_window_progress = _cache_symbol_progress(
        base_dir / DEFAULT_MANIFEST_DIR.parent,
        min_days=252,
        start_date="2024-06-01",
        end_date="2026-06-04",
    )
    full_ready = sum(1 for row in full_window_progress if row.get("ready"))
    empty_chunks = sum(int(row.get("empty_cache_chunks") or 0) for row in full_window_progress)
    checks.append(
        {
            "name": "historical_bar_full_window_cache",
            "ok": full_ready >= min_historical_symbols,
            "required": False,
            "detail": f"ready={full_ready}/{min_historical_symbols} empty_chunks={empty_chunks}",
        }
    )

    model_status = _model_candidate_status()
    checks.append(
        {
            "name": "historical_bar_model_candidates",
            "ok": set(model_status["ready_labels"]) >= {"triple_barrier_label", "trend_scan_label"},
            "required": True,
            "detail": json.dumps(model_status, sort_keys=True),
        }
    )

    print()
    print("=" * 72)
    print("  Monday Readiness Checklist")
    print("=" * 72)
    print(f"report_version          : {MONDAY_READINESS_VERSION}")
    print("runtime_effect          : report_only_no_live_authority")
    print(f"base_dir                : {base_dir}")
    print()
    print("Checks")
    for check in checks:
        status = "OK" if check["ok"] else "BLOCK" if check.get("required") else "WARN"
        requirement = "required" if check.get("required") else "advisory"
        print(f"  {status:<5} {requirement:<8} {check['name']:<36} {check['detail']}")

    ok = all(bool(check["ok"]) for check in checks if check.get("required"))
    print()
    if ok:
        print("[OK] Monday readiness checklist passed")
        return True
    print("[WARN] Monday readiness checklist has open items")
    return False
