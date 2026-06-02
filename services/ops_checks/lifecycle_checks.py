"""Lifecycle analysis operator check."""

from __future__ import annotations

from pathlib import Path

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.lifecycle_analysis_service import LifecycleAnalysisService


def _fmt(value) -> str:
    return "-" if value is None else str(value)


def run_lifecycle_analysis(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    samples: int = 15,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Canonical Lifecycle Analysis — {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    service = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    payload = service.payload(
        start_date=target_date,
        symbol=symbol,
    )

    if payload.symbol:
        print(f"symbol            : {payload.symbol}")
    for key, value in payload.summary.items():
        print(f"{key:<22}: {value}")

    if not payload.rows:
        print("[WARN] no canonical lifecycle rows found")
        return False

    print()
    print("Recent lifecycle samples:")
    print(
        f"  {'time':<25} {'sym':<6} {'act':<4} {'status':<33} "
        f"{'exit':<18} {'pnl':>8} {'rej60':>8}"
    )
    print(
        f"  {'-'*25} {'-'*6} {'-'*4} {'-'*33} "
        f"{'-'*18} {'-'*8} {'-'*8}"
    )
    for row in payload.rows[:samples]:
        print(
            f"  {str(row.get('decision_time') or '-')[:25]:<25} "
            f"{str(row.get('symbol') or '-'):<6} "
            f"{str(row.get('action') or '-'):<4} "
            f"{row.get('lifecycle_status'):<33} "
            f"{str(row.get('exit_trigger') or '-')[:18]:<18} "
            f"{_fmt(row.get('realized_pnl')):>8} "
            f"{_fmt(row.get('rejected_return_60m')):>8}"
        )

    snapshot_only = payload.summary.get("rejected_snapshot_only_no_trade", 0)
    if snapshot_only:
        print()
        print(
            f"[INFO] {snapshot_only} rejected snapshot-only row(s) have no trade_id; "
            "trade-row forward outcome backfill cannot link them"
        )

    matched_without_snapshot = payload.summary.get(
        "approved_matched_exit_missing_snapshot", 0
    )
    if matched_without_snapshot:
        print()
        print(
            f"[INFO] {matched_without_snapshot} approved row(s) have matched exits "
            "but no canonical exit snapshot; run/repair exit snapshot capture for "
            "full lifecycle attribution"
        )

    open_or_unlinked = payload.summary.get("approved_open_or_unlinked_exit", 0)
    if open_or_unlinked:
        print()
        print(
            f"[WARN] {open_or_unlinked} approved row(s) are still open or lack "
            "matched exit linkage"
        )
        return False

    missing_counterfactual = payload.summary["rejected_without_counterfactual"]
    if missing_counterfactual:
        print()
        print(
            f"[WARN] {missing_counterfactual} trade-backed rejected row(s) are missing forward outcomes"
        )
        return False

    print()
    print("[OK] lifecycle rows are analysis-ready for this date")
    return True
