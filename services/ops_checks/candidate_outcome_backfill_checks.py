"""Operator command for candidate-universe forward outcome backfill."""

from __future__ import annotations

from pathlib import Path

from repositories.candidate_universe_repo import CandidateUniverseRepository
from services.candidate_outcome_backfill_service import CandidateOutcomeBackfillService


def _pct(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return str(value)


def run_candidate_outcome_backfill(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Candidate Outcome Backfill - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    service = CandidateOutcomeBackfillService(CandidateUniverseRepository(db_path))
    result = service.backfill(
        target_date,
        symbol=symbol,
        limit=limit,
        dry_run=dry_run,
        overwrite=overwrite,
    )

    print(f"report_version       : {result.report_version}")
    print(f"runtime_effect       : {result.runtime_effect}")
    print(f"date                 : {result.date}")
    print(f"dry_run              : {result.dry_run}")
    if symbol:
        print(f"symbol               : {symbol.upper()}")
    print(f"rows                 : {result.rows}")
    print(f"eligible             : {result.eligible}")
    print(f"updated              : {result.updated}")
    print(f"skipped_existing     : {result.skipped_existing}")
    print(f"partial              : {result.partial}")
    print(f"no_bars              : {result.no_bars}")
    print(f"error                : {result.error}")
    print()
    print("Forward outcome coverage")
    before = result.coverage_before
    after = result.projected_coverage_after
    print(
        "  before             : "
        f"{before['rows_with_forward_outcome']} / {before['rows']} "
        f"({_pct(before['forward_outcome_coverage_rate'])})"
    )
    print(
        "  projected_after    : "
        f"{after['rows_with_forward_outcome']} / {after['rows']} "
        f"({_pct(after['forward_outcome_coverage_rate'])})"
    )
    print(
        "  non_taken_after    : "
        f"{after['non_taken_with_forward_outcome']} / {after['non_taken_rows']} "
        f"({_pct(after['non_taken_forward_outcome_coverage_rate'])})"
    )
    print(f"  missing_after      : {after['missing_forward_outcome']}")
    print(f"  ready_80pct_after  : {bool((after['forward_outcome_coverage_rate'] or 0) >= 0.8)}")

    if result.error:
        print("[WARN] candidate outcome backfill had errors")
        return False
    if not result.rows:
        print("[WARN] no candidate rows found")
        return False

    print()
    print("[OK] candidate outcome backfill completed; no live authority changed")
    return True
