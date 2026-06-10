#!/usr/bin/env python3
"""Automated post-session learning evidence repair.

This pipeline step is analysis-only. It completes missed-buy candidate forward
outcomes and canonical exit snapshot linkage so learning reports do not depend
on manual backfill commands after normal after-close jobs.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from repositories.candidate_universe_repo import CandidateUniverseRepository  # noqa: E402
from repositories.exit_snapshot_repo import ExitSnapshotRepository  # noqa: E402
from services.exit_snapshot_backfill_service import ExitSnapshotBackfillService  # noqa: E402
from services.exit_snapshot_service import ExitSnapshotService  # noqa: E402
from services.intelligence.candidates.outcome_backfill import (  # noqa: E402
    CandidateOutcomeBackfillService,
)


@dataclass(frozen=True)
class LearningBackfillRepairResult:
    target_date: str
    candidate_passes: int
    candidate_updated: int
    candidate_errors: int
    candidate_coverage_rate: float | None
    exit_scanned: int
    exit_inserted: int

    @property
    def ok(self) -> bool:
        return self.candidate_errors == 0


def run_learning_backfill_repair(
    target_date: str,
    *,
    base_dir: Path = BASE_DIR,
    candidate_limit: int = 1000,
    candidate_target_coverage: float = 0.95,
    max_candidate_passes: int = 20,
    dry_run: bool = False,
) -> LearningBackfillRepairResult:
    db_path = base_dir / "trades.db"
    candidate_service = CandidateOutcomeBackfillService(CandidateUniverseRepository(db_path))
    exit_repo = ExitSnapshotRepository(db_path)
    exit_service = ExitSnapshotBackfillService(exit_repo, ExitSnapshotService(exit_repo))

    candidate_passes = 0
    candidate_updated = 0
    candidate_errors = 0
    candidate_coverage_rate: float | None = None

    for _ in range(max(0, int(max_candidate_passes))):
        result = candidate_service.backfill(
            target_date,
            limit=max(1, int(candidate_limit)),
            dry_run=dry_run,
        )
        candidate_passes += 1
        candidate_updated += int(result.updated or 0)
        candidate_errors += int(result.error or 0)
        candidate_coverage_rate = result.projected_coverage_after.get(
            "forward_outcome_coverage_rate"
        )

        if candidate_errors:
            break
        if candidate_coverage_rate is not None and candidate_coverage_rate >= float(
            candidate_target_coverage
        ):
            break
        if int(result.updated or 0) <= 0:
            break
        if int(result.eligible or 0) < int(candidate_limit):
            break

    exit_result = exit_service.backfill_approved_matched_exits(
        start_date=target_date,
        dry_run=dry_run,
    )

    return LearningBackfillRepairResult(
        target_date=target_date,
        candidate_passes=candidate_passes,
        candidate_updated=candidate_updated,
        candidate_errors=candidate_errors,
        candidate_coverage_rate=candidate_coverage_rate,
        exit_scanned=exit_result.scanned,
        exit_inserted=exit_result.inserted,
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--candidate-limit", type=int, default=1000)
    parser.add_argument("--candidate-target-coverage", type=float, default=0.95)
    parser.add_argument("--max-candidate-passes", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = run_learning_backfill_repair(
        args.date,
        candidate_limit=args.candidate_limit,
        candidate_target_coverage=args.candidate_target_coverage,
        max_candidate_passes=args.max_candidate_passes,
        dry_run=args.dry_run,
    )

    print()
    print("=" * 72)
    print("  Learning Backfill Repair")
    print("=" * 72)
    print("runtime_effect              : analysis_repair_only_no_live_authority")
    print(f"date                        : {result.target_date}")
    print(f"dry_run                     : {args.dry_run}")
    print(f"candidate_passes            : {result.candidate_passes}")
    print(f"candidate_updated           : {result.candidate_updated}")
    print(f"candidate_errors            : {result.candidate_errors}")
    print(f"candidate_coverage_rate     : {_pct(result.candidate_coverage_rate)}")
    print(f"exit_snapshot_scanned       : {result.exit_scanned}")
    print(f"exit_snapshot_inserted      : {result.exit_inserted}")

    if result.ok:
        print()
        print("[OK] learning backfill repair completed")
        return 0
    print()
    print("[WARN] learning backfill repair completed with candidate errors")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
