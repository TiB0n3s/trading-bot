"""Tests for automated post-session learning backfill repair."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "trading_bot"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from pipeline import learning_backfill_repair as module


class FakeCandidateService:
    instances = []

    def __init__(self, repository):
        self.repository = repository
        self.calls = 0
        self.instances.append(self)

    def backfill(self, target_date, *, limit=None, dry_run=False):
        self.calls += 1
        coverage = 0.50 + (self.calls * 0.25)
        return SimpleNamespace(
            updated=100,
            error=0,
            eligible=100,
            projected_coverage_after={"forward_outcome_coverage_rate": coverage},
        )


class FakeExitSnapshotBackfillService:
    def __init__(self, repository, exit_snapshot_service):
        self.repository = repository
        self.exit_snapshot_service = exit_snapshot_service

    def backfill_approved_matched_exits(self, *, start_date, dry_run=False):
        return SimpleNamespace(scanned=2, inserted=2)


def test_learning_backfill_repair_loops_until_candidate_coverage_target():
    FakeCandidateService.instances = []
    original_candidate_service = module.CandidateOutcomeBackfillService
    original_exit_service = module.ExitSnapshotBackfillService
    original_policy_repair = module.repair_decision_policy_learning_effects
    module.CandidateOutcomeBackfillService = FakeCandidateService
    module.ExitSnapshotBackfillService = FakeExitSnapshotBackfillService
    module.repair_decision_policy_learning_effects = lambda *args, **kwargs: 3

    try:
        result = module.run_learning_backfill_repair(
            "2026-06-09",
            candidate_limit=100,
            candidate_target_coverage=0.95,
            max_candidate_passes=5,
        )
    finally:
        module.CandidateOutcomeBackfillService = original_candidate_service
        module.ExitSnapshotBackfillService = original_exit_service
        module.repair_decision_policy_learning_effects = original_policy_repair

    assert result.ok is True
    assert result.candidate_passes == 2
    assert result.candidate_updated == 200
    assert result.candidate_coverage_rate == 1.0
    assert result.decision_policy_repaired == 3
    assert result.exit_scanned == 2
    assert result.exit_inserted == 2
    assert FakeCandidateService.instances[0].calls == 2


if __name__ == "__main__":
    test_learning_backfill_repair_loops_until_candidate_coverage_target()
    print("learning backfill repair pipeline tests passed")
