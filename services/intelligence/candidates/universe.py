"""Candidate-universe capture for counterfactual learning.

The service has no trading authority. It records what was scored, including
near-threshold and not-taken candidates, so later reports can measure missed
opportunities and selection bias explicitly.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from repositories.candidate_universe_repo import CandidateUniverseRepository

CANDIDATE_UNIVERSE_CONTRACT_VERSION = "candidate_universe_v1"
ALLOWED_CANDIDATE_KINDS = {"entry", "exit"}
ALLOWED_CANDIDATE_STATUSES = {
    "taken",
    "scored_not_taken",
    "near_threshold",
    "exit_considered_not_taken",
}


@dataclass(frozen=True)
class CandidateCapture:
    candidate_ts: str
    symbol: str
    action: str
    candidate_kind: str
    candidate_status: str
    score: float | None = None
    threshold: float | None = None
    threshold_distance: float | None = None
    decision: str | None = None
    reason: str | None = None
    source: str | None = None
    setup_label: str | None = None
    regime: str | None = None
    session_phase: str | None = None
    canonical_intelligence_hash: str | None = None
    canonical_intelligence_version: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class CandidateUniverseService:
    def __init__(self, repository: CandidateUniverseRepository | None = None):
        self.repository = repository or CandidateUniverseRepository()

    @staticmethod
    def classify_status(
        *,
        taken: bool = False,
        score: float | None = None,
        threshold: float | None = None,
        near_threshold_pct: float = 0.10,
        candidate_kind: str = "entry",
    ) -> str:
        if taken:
            return "taken"
        if candidate_kind == "exit":
            return "exit_considered_not_taken"
        if score is not None and threshold not in (None, 0):
            distance = abs(float(score) - float(threshold))
            if distance <= abs(float(threshold)) * near_threshold_pct:
                return "near_threshold"
        return "scored_not_taken"

    def persist(self, capture: CandidateCapture) -> int:
        kind = str(capture.candidate_kind or "").strip().lower()
        status = str(capture.candidate_status or "").strip().lower()
        if kind not in ALLOWED_CANDIDATE_KINDS:
            raise ValueError(f"invalid candidate_kind={capture.candidate_kind!r}")
        if status not in ALLOWED_CANDIDATE_STATUSES:
            raise ValueError(f"invalid candidate_status={capture.candidate_status!r}")

        payload = {
            "contract_version": CANDIDATE_UNIVERSE_CONTRACT_VERSION,
            **capture.payload,
        }
        row = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "candidate_ts": capture.candidate_ts,
            "symbol": capture.symbol.upper(),
            "action": capture.action.lower(),
            "candidate_kind": kind,
            "candidate_status": status,
            "score": capture.score,
            "threshold": capture.threshold,
            "threshold_distance": capture.threshold_distance,
            "decision": capture.decision,
            "reason": capture.reason,
            "source": capture.source,
            "setup_label": capture.setup_label,
            "regime": capture.regime,
            "session_phase": capture.session_phase,
            "canonical_intelligence_hash": capture.canonical_intelligence_hash,
            "canonical_intelligence_version": capture.canonical_intelligence_version,
            "candidate_json": json.dumps(payload, sort_keys=True, default=str),
            "runtime_effect": "candidate_capture_only_no_live_authority",
        }
        return self.repository.insert_candidate(row)

    def persist_scored_candidate(
        self,
        *,
        candidate_ts: str,
        symbol: str,
        action: str,
        score: float | None,
        threshold: float | None,
        taken: bool,
        payload: dict[str, Any] | None = None,
        candidate_kind: str = "entry",
        **metadata: Any,
    ) -> int:
        threshold_distance = (
            round(float(score) - float(threshold), 4)
            if score is not None and threshold is not None
            else None
        )
        status = self.classify_status(
            taken=taken,
            score=score,
            threshold=threshold,
            candidate_kind=candidate_kind,
        )
        return self.persist(
            CandidateCapture(
                candidate_ts=candidate_ts,
                symbol=symbol,
                action=action,
                candidate_kind=candidate_kind,
                candidate_status=status,
                score=score,
                threshold=threshold,
                threshold_distance=threshold_distance,
                payload=payload or {},
                **metadata,
            )
        )

    def rows_for_date(
        self,
        target_date: str,
        *,
        symbol: str | None = None,
        candidate_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.repository.rows_for_date(
                target_date,
                symbol=symbol,
                candidate_kind=candidate_kind,
            )
        ]


def candidate_capture_to_dict(capture: CandidateCapture) -> dict[str, Any]:
    return asdict(capture)
