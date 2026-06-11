"""Paper-session evidence aggregation for ML/intelligence authority review."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from repositories.paper_session_evidence_repo import PaperSessionEvidenceRepository
from services.intelligence.candidates.outcome_coverage import (
    summarize_candidate_outcome_coverage,
)

PAPER_SESSION_EVIDENCE_VERSION = "paper_session_evidence_v1"
PAPER_SESSION_EVIDENCE_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"


@dataclass(frozen=True)
class PaperSessionEvidence:
    report_version: str
    runtime_effect: str
    target_date: str
    decision_snapshots: dict[str, Any]
    auto_buy: dict[str, Any]
    candidate_universe: dict[str, Any]
    outcomes: dict[str, Any]
    blockers: list[str] = field(default_factory=list)

    @property
    def clean_for_authority_review(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["clean_for_authority_review"] = self.clean_for_authority_review
        return payload


def build_paper_session_evidence_payload(
    *,
    db_path: Path,
    target_date: str,
    min_candidate_forward_coverage: float = 0.80,
) -> PaperSessionEvidence:
    repo = PaperSessionEvidenceRepository(db_path)
    if not repo.exists():
        return PaperSessionEvidence(
            report_version=PAPER_SESSION_EVIDENCE_VERSION,
            runtime_effect=PAPER_SESSION_EVIDENCE_RUNTIME_EFFECT,
            target_date=target_date,
            decision_snapshots={"rows": 0},
            auto_buy={"candidate_rows": 0, "decision_snapshot_rows": 0},
            candidate_universe={"rows": 0},
            outcomes={"matched_trades": 0, "rejected_completed": 0},
            blockers=[f"missing_database:{db_path}"],
        )

    decision_rows = repo.count(
        "decision_snapshots",
        date_column="decision_time",
        target_date=target_date,
    )
    policy_effect_rows = repo.decision_policy_learning_effect_rows(target_date)
    auto_buy_candidate_rows = repo.count(
        "auto_buy_candidates",
        date_column="timestamp",
        target_date=target_date,
    )
    auto_buy_snapshot_rows = repo.count(
        "auto_buy_decision_snapshots",
        date_column="candidate_timestamp",
        target_date=target_date,
    )
    auto_buy_submitted = repo.count(
        "auto_buy_decision_snapshots",
        date_column="candidate_timestamp",
        target_date=target_date,
        extra_where="order_submitted = 1",
    )
    bridge_routed = (
        repo.count(
            "auto_buy_decision_snapshots",
            date_column="candidate_timestamp",
            target_date=target_date,
            extra_where="execution_status = 'ROUTED'",
        )
        if repo.has_column("auto_buy_decision_snapshots", "execution_status")
        else 0
    )
    intraday_feedback_rows = repo.count(
        "auto_buy_intraday_feedback",
        date_column="created_at",
        target_date=target_date,
    )
    rejected_completed_where = (
        "label_status = 'COMPLETED'"
        if repo.has_column("rejected_signal_outcomes", "label_status")
        else ""
    )
    rejected_completed = repo.count(
        "rejected_signal_outcomes",
        date_column="created_at",
        target_date=target_date,
        extra_where=rejected_completed_where,
    )
    matched_trades = repo.count(
        "matched_trades",
        date_column="entry_timestamp",
        target_date=target_date,
    )
    candidates = repo.candidate_rows(target_date)

    coverage = summarize_candidate_outcome_coverage(candidates)
    coverage_rate = coverage.get("forward_outcome_coverage_rate")

    blockers: list[str] = []
    if decision_rows <= 0:
        blockers.append("decision_snapshots_missing")
    if candidates and (
        coverage_rate is None or float(coverage_rate) < min_candidate_forward_coverage
    ):
        blockers.append("candidate_forward_outcome_coverage_below_80pct")
    if decision_rows and policy_effect_rows <= 0:
        blockers.append("decision_policy_learning_effect_not_recorded")

    return PaperSessionEvidence(
        report_version=PAPER_SESSION_EVIDENCE_VERSION,
        runtime_effect=PAPER_SESSION_EVIDENCE_RUNTIME_EFFECT,
        target_date=target_date,
        decision_snapshots={
            "rows": decision_rows,
            "decision_policy_learning_effect_rows": policy_effect_rows,
        },
        auto_buy={
            "candidate_rows": auto_buy_candidate_rows,
            "decision_snapshot_rows": auto_buy_snapshot_rows,
            "submitted_rows": auto_buy_submitted,
            "bridge_routed_rows": bridge_routed,
            "intraday_feedback_rows": intraday_feedback_rows,
        },
        candidate_universe=coverage,
        outcomes={
            "matched_trades": matched_trades,
            "rejected_completed": rejected_completed,
        },
        blockers=blockers,
    )
