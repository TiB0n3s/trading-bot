#!/usr/bin/env python3
"""Automated post-session learning evidence repair.

This pipeline step is analysis-only. It completes missed-buy candidate forward
outcomes and canonical exit snapshot linkage so learning reports do not depend
on manual backfill commands after normal after-close jobs.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
for path in (
    BASE_DIR / "src" / "trading_bot",
    BASE_DIR / "scripts",
    BASE_DIR,
):
    path_str = str(path)
    if path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from repositories.candidate_universe_repo import CandidateUniverseRepository  # noqa: E402
from repositories.decision_snapshot_repo import DecisionSnapshotRepository  # noqa: E402
from repositories.exit_snapshot_repo import ExitSnapshotRepository  # noqa: E402
from services.canonical_intelligence_service import (  # noqa: E402
    CANONICAL_INTELLIGENCE_VERSION,
    _decision_policy_outcome,
    stable_canonical_hash,
    stable_canonical_json,
)
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
    decision_policy_repaired: int
    exit_scanned: int
    exit_inserted: int

    @property
    def ok(self) -> bool:
        return self.candidate_errors == 0


def _load_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def repair_decision_policy_learning_effects(
    db_path: Path,
    target_date: str,
    *,
    dry_run: bool = False,
) -> int:
    repository = DecisionSnapshotRepository(db_path)
    rows = repository.list_canonical_repair_rows(target_date)

    updates: list[tuple[str, str, str, int]] = []
    for row in rows:
        canonical = _load_json(row["canonical_intelligence_json"])
        account_state = _load_json(row["account_state_json"])
        advisory = (
            canonical.get("advisory_authority_state", {})
            .get("decision_policy_outcome", {})
            .get("advisory_decision")
        )
        if str(advisory or "").strip():
            continue
        outcome = _decision_policy_outcome(account_state)
        if not str(outcome.get("advisory_decision") or "").strip():
            continue
        advisory_state = canonical.setdefault("advisory_authority_state", {})
        if not isinstance(advisory_state, dict):
            advisory_state = {}
            canonical["advisory_authority_state"] = advisory_state
        advisory_state["decision_policy_outcome"] = outcome
        canonical["version"] = canonical.get("version") or CANONICAL_INTELLIGENCE_VERSION
        canonical_json = stable_canonical_json(canonical)
        canonical_hash = stable_canonical_hash(canonical)
        updates.append(
            (
                CANONICAL_INTELLIGENCE_VERSION,
                canonical_hash,
                canonical_json,
                int(row["id"]),
            )
        )

    if updates and not dry_run:
        repository.update_canonical_intelligence_many(updates)
    return len(updates)


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
    decision_policy_repaired = repair_decision_policy_learning_effects(
        db_path,
        target_date,
        dry_run=dry_run,
    )

    return LearningBackfillRepairResult(
        target_date=target_date,
        candidate_passes=candidate_passes,
        candidate_updated=candidate_updated,
        candidate_errors=candidate_errors,
        candidate_coverage_rate=candidate_coverage_rate,
        decision_policy_repaired=decision_policy_repaired,
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
    print(f"decision_policy_repaired    : {result.decision_policy_repaired}")
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
