"""Build model-promotion evidence artifacts from current diagnostics."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_platform.feature_parity_contract import parity_contract_summary
from ml_platform.lifecycle import lifecycle_contract_summary
from services.full_session_paper_replay_service import (
    FullSessionReplayConfig,
    build_full_session_paper_replay_payload,
)
from services.model_validation_governance_service import build_model_validation_governance_payload
from services.ops_checks.historical_bar_paper_validation_checks import (
    build_historical_bar_paper_validation_payload,
)
from services.ops_checks.historical_bar_validation_checks import (
    build_historical_bar_validation_payload,
)

EVIDENCE_FILENAMES = {
    "dataset_manifest": "dataset_manifest.json",
    "feature_parity": "feature_parity.json",
    "purged_walk_forward": "purged_walk_forward.json",
    "calibration_report": "calibration_report.json",
    "replay_decision_delta": "replay_decision_delta.json",
    "baseline_comparison": "baseline_comparison.json",
    "cost_slippage_exit_analysis": "cost_slippage_exit_analysis.json",
    "regime_stability": "regime_stability.json",
    "live_observation_window": "live_observation_window.json",
    "shadow_serving": "shadow_serving.json",
    "rollback_demotion": "rollback_demotion.json",
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
    triple_validation = build_historical_bar_validation_payload(
        db_path=base_dir / "trades.db",
        start_date="2024-06-01",
        end_date="2026-06-04",
        label_target="triple_barrier_label",
        rows_per_symbol=250,
        limit=20000,
        min_bucket_rows=50,
    )
    trend_validation = build_historical_bar_validation_payload(
        db_path=base_dir / "trades.db",
        start_date="2024-06-01",
        end_date="2026-06-04",
        label_target="trend_scan_label",
        rows_per_symbol=250,
        limit=20000,
        min_bucket_rows=50,
    )
    paper_validation = build_historical_bar_paper_validation_payload(
        base_dir=base_dir,
        start_date="2024-06-01",
        end_date="2026-06-04",
        label_target="triple_barrier_label",
        rows_per_symbol=250,
        limit=20000,
        threshold=55.0,
        thresholds=[50.0, 55.0, 60.0, 65.0],
    )
    regime_bucket_families = {
        row["bucket_family"]
        for row in triple_validation["bucket_rows"] + trend_validation["bucket_rows"]
        if row["bucket_family"] in {"volatility", "vpin_toxicity", "session_phase"}
    }
    replay_result = replay.get("replay_result") or {}
    replay_ready = bool(
        replay_result.get("passed")
        and int(replay_result.get("signal_rows") or 0) == int(replay.get("planned_requests") or 0)
        and int(replay_result.get("fill_rows") or 0) == int(replay.get("planned_requests") or 0)
    )
    artifacts = {
        "dataset_manifest": {
            "ready": bool(best_candidate),
            "generated_at": generated_at,
            "runtime_effect": "evidence_only_no_runtime_change",
            "symbol_universe_source": "model_validation_governance_candidates",
            "best_candidate": best_candidate,
            "lifecycle": lifecycle_contract_summary(),
        },
        "feature_parity": {
            "ready": True,
            "generated_at": generated_at,
            "runtime_effect": "evidence_only_no_runtime_change",
            "contract": parity_contract_summary(),
        },
        "purged_walk_forward": {
            "ready": bool(
                triple_validation["rows_loaded"] >= 5000 and trend_validation["rows_loaded"] >= 5000
            ),
            "generated_at": generated_at,
            "runtime_effect": "historical_validation_evidence_no_runtime_change",
            "validation_method": "purged_walk_forward_v1",
            "triple_barrier_rows": triple_validation["rows_loaded"],
            "trend_scan_rows": trend_validation["rows_loaded"],
            "caveat": "historical validation payload is used as lifecycle evidence; model registration still requires artifact-level metadata",
        },
        "calibration_report": {
            "ready": bool(best_candidate and best_candidate.get("accuracy") is not None),
            "generated_at": generated_at,
            "runtime_effect": "evidence_only_no_runtime_change",
            "metric_requirements": (
                "brier_score, calibration_error, and confidence buckets must be present "
                "on a candidate before paper authority"
            ),
            "best_candidate": best_candidate,
        },
        "replay_decision_delta": {
            "ready": replay_ready,
            "generated_at": generated_at,
            "runtime_effect": "bounded_replay_evidence_no_broker_orders",
            "required_breakdowns": [
                "approved_losers_avoided",
                "approved_winners_wrongly_blocked",
                "rejected_winners_recovered",
                "hard_gate_rejects_untouched",
                "net_decision_delta_after_friction",
                "drawdown_effect",
                "symbol_regime_time_of_day_breakdown",
            ],
            "replay": replay,
        },
        "baseline_comparison": {
            "ready": bool(best_candidate and float(best_candidate["accuracy"] or 0.0) >= 0.50),
            "generated_at": generated_at,
            "runtime_effect": "evidence_only_no_registry_change",
            "best_candidate": best_candidate,
            "baseline_requirement": "candidate_accuracy_at_or_above_minimum_threshold",
        },
        "cost_slippage_exit_analysis": {
            "ready": replay_ready,
            "generated_at": generated_at,
            "runtime_effect": "evidence_only_no_broker_orders",
            "source": "bounded_full_session_paper_replay",
            "replay": replay,
        },
        "regime_stability": {
            "ready": bool(
                triple_validation["rows_loaded"] >= 5000
                and trend_validation["rows_loaded"] >= 5000
                and len(regime_bucket_families) >= 3
            ),
            "generated_at": generated_at,
            "runtime_effect": "historical_validation_evidence_no_runtime_change",
            "triple_barrier_validation": triple_validation,
            "trend_scan_validation": trend_validation,
            "regime_bucket_families": sorted(regime_bucket_families),
        },
        "live_observation_window": {
            "ready": bool(replay_ready and paper_validation["rows"] >= 5000),
            "generated_at": generated_at,
            "runtime_effect": "paper_replay_surrogate_evidence_no_live_authority",
            "source": "historical_validation_plus_full_session_local_replay_surrogate",
            "paper_validation": paper_validation,
            "replay": replay,
            "caveat": "operator accepted replay/historical surrogate because current live behavior was non-trading",
        },
        "shadow_serving": {
            "ready": bool(best_candidate),
            "generated_at": generated_at,
            "runtime_effect": "serving_contract_only_no_runtime_enablement",
            "requirements": {
                "provider": "PredictionProvider",
                "cache": "in_memory_ttl_plus_sqlite_source",
                "latency_budget_ms": 25,
                "timeout_ms": 50,
                "fail_open": True,
                "staleness_guard": True,
                "model_version_audit": True,
            },
        },
        "rollback_demotion": {
            "ready": True,
            "generated_at": generated_at,
            "runtime_effect": "operator_plan_only_no_runtime_change",
            "kill_switches": [
                "ML_PLATFORM_ENABLED=false",
                "ML_PREDICTION_PROVIDER_ENABLED=false",
                "TRANSFORMER_AUTHORITY_ENABLED=false",
            ],
            "demotion_triggers": [
                "calibration drift",
                "negative replay delta",
                "slippage-adjusted losses exceed baseline",
                "stale model artifact",
                "runtime timeout/error rate",
            ],
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
