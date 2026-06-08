"""Build model-promotion evidence artifacts from current diagnostics."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.full_session_paper_replay_service import (
    FullSessionReplayConfig,
    build_full_session_paper_replay_payload,
)
from services.model_validation_governance_service import build_model_validation_governance_payload

EVIDENCE_FILENAMES = {
    "baseline_comparison": "baseline_comparison.json",
    "cost_slippage_exit_analysis": "cost_slippage_exit_analysis.json",
    "regime_stability": "regime_stability.json",
    "live_observation_window": "live_observation_window.json",
    "operator_approval": "operator_approval.json",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_model_promotion_evidence_payload(
    *,
    base_dir: Path,
    write: bool = False,
    operator: str = "unassigned",
    approval_reference: str = "",
    replay_symbols: tuple[str, ...] = ("AAPL",),
    execute_replay: bool = False,
    max_replay_requests: int = 1000,
) -> dict[str, Any]:
    evidence_dir = base_dir / "ops" / "model_promotion_evidence"
    generated_at = _utc_now()
    governance = build_model_validation_governance_payload(
        promotion_evidence_dir=evidence_dir,
    )
    ready_candidates = [
        row for row in governance["candidates"] if row["status"] == "observe_only_ready"
    ]
    best_candidate = max(
        ready_candidates,
        key=lambda row: float(row["accuracy"] or 0.0),
        default=None,
    )
    replay = build_full_session_paper_replay_payload(
        FullSessionReplayConfig(
            symbols=replay_symbols,
            execute=execute_replay,
            max_execute_requests=max_replay_requests,
        )
    )
    artifacts = {
        "baseline_comparison": {
            "ready": bool(best_candidate and float(best_candidate["accuracy"] or 0.0) >= 0.50),
            "generated_at": generated_at,
            "runtime_effect": "evidence_only_no_registry_change",
            "best_candidate": best_candidate,
            "baseline_requirement": "candidate_accuracy_at_or_above_minimum_threshold",
        },
        "cost_slippage_exit_analysis": {
            "ready": bool(replay.get("replay_result") and replay["replay_result"].get("passed")),
            "generated_at": generated_at,
            "runtime_effect": "evidence_only_no_broker_orders",
            "source": "bounded_full_session_paper_replay",
            "replay": replay,
        },
        "regime_stability": {
            "ready": False,
            "generated_at": generated_at,
            "runtime_effect": "evidence_placeholder_no_runtime_change",
            "reason": "requires multi-session paper evidence across at least two regimes",
        },
        "live_observation_window": {
            "ready": False,
            "generated_at": generated_at,
            "runtime_effect": "evidence_placeholder_no_runtime_change",
            "reason": "requires required live/paper observation-window artifact from market sessions",
        },
        "operator_approval": {
            "ready": bool(operator and operator != "unassigned" and approval_reference),
            "generated_at": generated_at,
            "runtime_effect": "operator_record_only_no_runtime_change",
            "operator": operator,
            "approval_reference": approval_reference,
        },
    }
    if write:
        for key, filename in EVIDENCE_FILENAMES.items():
            _write_json(evidence_dir / filename, artifacts[key])
    return {
        "report_version": "model_promotion_evidence_v1",
        "runtime_effect": "evidence_generation_no_registry_or_runtime_authority_change",
        "evidence_dir": str(evidence_dir),
        "write": write,
        "artifact_count": len(artifacts),
        "ready_count": sum(1 for row in artifacts.values() if row.get("ready") is True),
        "artifacts": artifacts,
        "ready_for_live_promotion": all(row.get("ready") is True for row in artifacts.values()),
    }
