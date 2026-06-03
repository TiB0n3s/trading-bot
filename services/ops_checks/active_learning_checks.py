"""Operator report for active learning integration."""

from __future__ import annotations

import json
from pathlib import Path

from repositories import auto_buy_repo
from repositories.candidate_universe_repo import CandidateUniverseRepository
from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.active_learning_integration_service import (
    build_active_learning_integration_payload,
)
from services.lifecycle_analysis_service import LifecycleAnalysisService


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _load_strategy_memory(base_dir: Path) -> dict:
    path = base_dir / "strategy_memory.json"
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text())
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def run_active_learning_integration(
    start_date: str,
    *,
    end_date: str | None,
    base_dir: Path,
    symbol: str | None = None,
) -> bool:
    end = end_date or start_date
    print()
    print("=" * 72)
    print(f"  Active Learning Integration - {start_date} to {end}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(
        start_date=start_date,
        end_date=end,
        symbol=symbol,
    )
    auto_buy_rows = [
        dict(row)
        for row in auto_buy_repo.decision_snapshot_rows_between(
            start_date,
            end,
            symbol=symbol,
            db_path=db_path,
        )
    ]
    candidate_rows = [
        dict(row)
        for row in CandidateUniverseRepository(db_path).rows_between(
            start_date,
            end,
            symbol=symbol,
        )
    ]
    payload = build_active_learning_integration_payload(
        lifecycle_rows=lifecycle_payload.rows,
        auto_buy_rows=auto_buy_rows,
        candidate_rows=candidate_rows,
        strategy_memory=_load_strategy_memory(base_dir),
        start_date=start_date,
        end_date=end,
    )

    print(f"report_version              : {payload.summary['report_version']}")
    print(f"runtime_effect              : {payload.summary['runtime_effect']}")
    print(f"actively_learning           : {payload.summary['actively_learning']}")
    print(f"active_learning_signal_count: {payload.summary['active_learning_signal_count']}")
    print(f"authority_note              : {payload.summary['authority_note']}")
    if symbol:
        print(f"symbol                      : {symbol.upper()}")

    print()
    print("Auto-buy path")
    for key, value in payload.auto_buy_path.items():
        print(f"  {key:<34} {_fmt(value)}")

    print()
    print("Lifecycle path")
    for key, value in payload.lifecycle_path.items():
        print(f"  {key:<34} {_fmt(value)}")

    print()
    print("Strategy memory")
    for key, value in payload.strategy_memory.items():
        if key == "sections":
            print(f"  {key:<34} {', '.join(value) if value else '-'}")
        else:
            print(f"  {key:<34} {_fmt(value)}")

    print()
    print("Candidate universe")
    for key, value in payload.candidate_universe.items():
        print(f"  {key:<34} {_fmt(value)}")

    if payload.blockers:
        print()
        print("Blockers")
        for blocker in payload.blockers:
            print(f"  - {blocker}")

    print()
    print("Next actions")
    for action in payload.next_actions:
        print(f"  - {action}")

    print()
    print("[OK] active learning integration report completed")
    return True
