"""Staged ML integration contracts.

This module wires together observe-only ML platform pieces for integration
testing. It is intentionally read-only and is not imported by live webhook,
broker, order, or risk-control paths.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import DB_PATH
from ml_platform.brain_features import brain_feature_manifest, build_brain_feature_rows
from ml_platform.datasets import dataset_profile
from ml_platform.governance import (
    APP_REFACTOR_RISK_POLICY,
    SERVING_LATENCY_CONTRACT,
    build_dataset_manifest,
)
from ml_platform.readiness import retraining_readiness_report
from ml_platform.replay import replay_decisions_scaffold
from ml_platform.serving import SQLitePredictionProvider


STAGED_INTEGRATION_VERSION = "staged_ml_integration_v1"
STAGED_RUNTIME_EFFECT = "none"
STAGED_STATUS = "staged_observe_only_no_runtime_effect"


@dataclass(frozen=True)
class StagedIntegrationReport:
    version: str
    generated_at: str
    status: str
    runtime_effect: str
    live_import_contract: str
    dataset_profile: dict[str, Any]
    dataset_manifest: dict[str, Any]
    brain_feature_manifest: dict[str, Any]
    replay_contract: dict[str, Any]
    prediction_provider_contract: dict[str, Any]
    retraining_readiness: dict[str, Any]
    promotion_gates: dict[str, Any]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def staged_ml_integration_report(
    *,
    db_path: Path | str = DB_PATH,
    start_date: str,
    end_date: str,
    candidate_model: str,
    policy: str = "current",
    prediction_symbol: str | None = None,
) -> dict[str, Any]:
    """Return a read-only staged integration report for ML platform contracts."""
    profile = dataset_profile(
        db_path=db_path,
        start_date=start_date,
        end_date=end_date,
    )
    manifest = build_dataset_manifest(
        db_path=db_path,
        start_date=start_date,
        end_date=end_date,
        query_version="staged_ml_integration_v1",
    )
    rows = build_brain_feature_rows(
        db_path=db_path,
        start_date=start_date,
        end_date=end_date,
    )
    provider = SQLitePredictionProvider(db_path=db_path)
    prediction = None
    if prediction_symbol and start_date == end_date:
        prediction = provider.get_prediction(start_date, prediction_symbol)

    report = StagedIntegrationReport(
        version=STAGED_INTEGRATION_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        status=STAGED_STATUS,
        runtime_effect=STAGED_RUNTIME_EFFECT,
        live_import_contract=(
            "Do not import this staged integration from app.py webhook, broker, "
            "order execution, or hard risk-control paths."
        ),
        dataset_profile=profile,
        dataset_manifest=manifest,
        brain_feature_manifest=brain_feature_manifest(rows),
        replay_contract=replay_decisions_scaffold(
            start_date=start_date,
            end_date=end_date,
            policy=policy,
            candidate_model=candidate_model,
        ),
        prediction_provider_contract={
            "provider": "SQLitePredictionProvider",
            "latency_budget_ms": provider.latency_budget_ms,
            "timeout_ms": provider.timeout_ms,
            "serving_latency_contract": SERVING_LATENCY_CONTRACT,
            "sample_prediction": prediction.to_dict() if prediction else None,
            "runtime_effect": STAGED_RUNTIME_EFFECT,
        },
        retraining_readiness=retraining_readiness_report(
            dataset_profile=profile,
            dataset_manifest=manifest,
            trading_sessions_observed=0,
        ),
        promotion_gates={
            "app_refactor_risk_policy": APP_REFACTOR_RISK_POLICY,
            "requires_live_flag_default_off": True,
            "requires_shadow_or_observe_only_period": True,
            "requires_operator_visible_report": True,
            "requires_no_broker_or_order_side_effects": True,
        },
        notes=(
            "Staged integration is for tests, reports, and operator review.",
            "It builds manifests, profiles, brain-feature summaries, replay contracts, and prediction-provider contracts.",
            "It does not train models, place orders, loosen risk controls, or write to trades.db.",
        ),
    )
    return report.to_dict()


def write_staged_report(report: dict[str, Any], output: Path | str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path
