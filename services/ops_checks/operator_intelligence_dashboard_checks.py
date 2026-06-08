"""Compact operator intelligence dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.historical_bar_training_repo import fetch_historical_bar_training_rows
from services.ops_checks.historical_bar_model_checks import (
    DEFAULT_CANDIDATE_DIR,
    _assess,
    _diagnostics,
    _latest_by_label,
)


OPERATOR_INTELLIGENCE_VERSION = "operator_intelligence_dashboard_v1"


def _age_hours(path: Path) -> float | None:
    if not path.exists():
        return None
    return round((datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600.0, 2)


def _candidate_status() -> dict[str, Any]:
    diagnostics = _diagnostics(DEFAULT_CANDIDATE_DIR)
    latest = _latest_by_label(diagnostics)
    assessed = {
        label: _assess(row, min_rows=5000, min_symbols=59, min_accuracy=0.50)
        for label, row in latest.items()
    }
    return {
        "diagnostics": len(diagnostics),
        "ready_labels": sorted(
            label for label, item in assessed.items() if item.status == "observe_only_candidate_ready"
        ),
        "failed_labels": {
            label: item.failed_thresholds for label, item in assessed.items() if item.failed_thresholds
        },
    }


def run_operator_intelligence_dashboard(
    *,
    base_dir: Path,
    target_date: str,
) -> bool:
    market_context = base_dir / "market_context.json"
    rows = fetch_historical_bar_training_rows(
        db_path=base_dir / "trades.db",
        start_date="2024-06-01",
        end_date=target_date,
        rows_per_symbol=1,
        limit=80,
    )
    symbols = sorted({str(row.get("symbol") or "") for row in rows if row.get("symbol")})
    model_status = _candidate_status()
    required_ok = bool(market_context.exists()) and len(symbols) >= 20 and len(model_status["ready_labels"]) >= 2
    print()
    print("=" * 72)
    print("  Operator Intelligence Dashboard")
    print("=" * 72)
    print(f"report_version          : {OPERATOR_INTELLIGENCE_VERSION}")
    print("runtime_effect          : dashboard_only_no_live_authority")
    print(f"target_date             : {target_date}")
    print(f"market_context_age_hours: {_age_hours(market_context)}")
    print(f"historical_symbols_seen : {len(symbols)}")
    print(f"model_diagnostics       : {model_status['diagnostics']}")
    print(f"ready_model_labels      : {', '.join(model_status['ready_labels']) or '-'}")
    print(f"failed_model_labels     : {model_status['failed_labels'] or '-'}")
    print()
    print("Next operator checks")
    print("  python3 ops_check.py monday-readiness")
    print(f"  python3 ops_check.py historical-bar-paper-validation 2024-06-01 --end-date {target_date}")
    print(f"  python3 ops_check.py historical-bar-walk-forward 2024-06-01 --end-date {target_date}")
    print(f"  python3 ops_check.py exit-intelligence {target_date}")
    print("  python3 ops_check.py sqlite-ownership")
    print()
    if required_ok:
        print("[OK] operator intelligence dashboard has core evidence")
        return True
    print("[WARN] operator intelligence dashboard has missing core evidence")
    return False
