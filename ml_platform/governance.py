"""Governance contracts for ML research and promotion.

This module is intentionally declarative and read-only. It defines the audit,
leakage, label, manifest, and promotion rules that future ML code must satisfy
before any runtime integration is considered.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_platform.config import DEFAULT_DB_PATH, FEATURE_VERSION
from repositories.training_data_repo import TrainingDataRepository


LEAKAGE_TIMEPOINTS = (
    "signal_time",
    "order_decision_time",
    "fill_time",
    "exit_time",
    "end_of_day",
    "next_session_open",
)

LEAKAGE_POLICY = {
    "rule": "Training features must only include information available at or before the row's feature_available_at timestamp.",
    "required_row_fields": (
        "feature_available_at",
        "feature_generated_at",
        "feature_age_seconds",
        "source",
        "is_stale",
        "staleness_reason",
    ),
    "decision_cutoff": "order_decision_time",
    "exclude_after_decision": (
        "matched outcomes",
        "post-decision daily_symbol_predictions",
        "market_context.json generated or edited after decision time",
        "position-manager exits",
        "trend/timing reports generated after the fact",
        "post-session labels",
    ),
    "timepoints": LEAKAGE_TIMEPOINTS,
}

DECISION_SNAPSHOT_FIELDS = (
    "signal_id",
    "timestamp",
    "symbol",
    "action",
    "price",
    "market_context_version",
    "macro_regime",
    "risk_multiplier",
    "setup_label",
    "setup_score",
    "trend_state",
    "momentum_state",
    "prediction_version",
    "risk_gate_outputs",
    "final_decision",
    "rejection_reason",
    "order_id",
    "git_sha",
    "env_profile_hash",
)

LABEL_TAXONOMY_V1 = {
    "version": "label_taxonomy_v1",
    "fixed_horizon_returns": {
        "ret_5m": "Raw symbol return 5 minutes after signal/candidate time.",
        "ret_15m": "Raw symbol return 15 minutes after signal/candidate time.",
        "ret_30m": "Raw symbol return 30 minutes after signal/candidate time.",
        "ret_60m": "Raw symbol return 60 minutes after signal/candidate time.",
        "ret_eod": "Raw symbol return from signal/candidate time to same-session close.",
    },
    "excursion_labels": {
        "max_favorable_excursion": "Best action-adjusted move available after the decision within the label horizon.",
        "max_adverse_excursion": "Worst action-adjusted move after the decision within the label horizon.",
        "time_to_profit": "Minutes until a configured favorable threshold was first touched.",
        "time_to_drawdown": "Minutes until a configured adverse threshold was first touched.",
    },
    "classification_labels": {
        "entry_quality_outcome": "good_entry, late_entry, early_entry, noisy_entry, or insufficient_data.",
        "would_hit_stop": "Whether the configured stop threshold would be touched before/within the horizon.",
        "would_hit_take_profit": "Whether the configured target threshold would be touched before/within the horizon.",
        "was_late_entry": "Whether most favorable move occurred before the bot entered or candidate fired.",
        "was_churn": "Whether the decision quickly reversed into an opposite signal/exit.",
        "was_bad_fill": "Whether execution materially worsened the signal/candidate price.",
        "was_correct_rejection": "Whether a rejected opportunity had poor forward return or unacceptable adverse excursion.",
    },
    "exit_policy_requirements": {
        "realized_pnl_labels": "Must include exit_policy_version and position_manager_version.",
        "fixed_horizon_labels": "Preferred for first training pass because they are less policy-dependent.",
    },
    "principle": "Keep signal quality, execution quality, exit policy, sizing, and market regime separable.",
}

REJECTED_SIGNAL_FORWARD_RETURNS = (
    "return_5m",
    "return_15m",
    "return_30m",
    "return_60m",
    "return_eod",
    "max_favorable_60m",
    "max_adverse_60m",
)

CANONICAL_SIGNAL_TIME_FEATURES = {
    "feature_version": "feature_snapshots_v3",
    "fields": {
        "momentum_acceleration_pct": {
            "source": "app.get_momentum/live_features bar snapshot",
            "available_at": "signal_time",
            "leakage_status": "allowed_signal_time",
        },
        "volume_surge_ratio": {
            "source": "app.get_momentum/live_features bar snapshot",
            "available_at": "signal_time",
            "leakage_status": "allowed_signal_time",
        },
        "extension_from_recent_base_pct": {
            "source": "rolling_momentum.json generated from recent bars",
            "available_at": "signal_time",
            "leakage_status": "allowed_if_context_fresh_at_signal_time",
        },
        "prior_session_return_pct": {
            "source": "strong_day_participation most recent prior row",
            "available_at": "signal_time",
            "leakage_status": "allowed_prior_session_only",
        },
    },
}

ORDER_FILL_TRUTH_HIERARCHY = (
    "alpaca_order_fill_data",
    "fill_stream",
    "fill_poller",
    "trades_table",
    "synthetic_matcher",
)

FILL_CONFIDENCE_VALUES = (
    "broker_confirmed",
    "reconstructed",
    "synthetic",
    "unknown",
)

MODEL_OUTPUT_CONTRACT = {
    "prediction": "avoid_entry",
    "confidence": 0.61,
    "abstain": False,
    "abstain_reason": None,
    "explanation_fields": (
        "top_positive_features",
        "top_negative_features",
        "missing_features",
        "similar_historical_cases",
        "regime_match",
        "confidence_calibration_bucket",
    ),
}

MIN_SAMPLE_GATES = {
    "symbol_level_claims": 30,
    "regime_level_claims": 100,
    "rejection_policy_claims": 20,
    "sizing_policy_claims": 50,
    "walk_forward_splits": 3,
}

BASELINE_POLICIES = (
    "always_approve",
    "always_reject",
    "null_no_ml_current_bot",
    "current_bot_policy",
    "current_claude_plus_deterministic_gates",
    "symbol_historical_average",
    "setup_label_average",
    "macro_regime_average",
    "previous_model_version",
    "randomized_policy_same_trade_count",
)

FRICTION_ASSUMPTIONS = (
    "spread_estimate",
    "slippage_estimate",
    "partial_fill_handling",
    "commission_placeholder",
    "latency_assumption",
    "market_order_vs_limit_order_behavior",
    "stop_loss_take_profit_execution_approximation",
)

CALIBRATION_BUCKETS = (
    "0.50-0.60",
    "0.60-0.70",
    "0.70-0.80",
    "0.80-0.90",
)

DRIFT_CHECKS = (
    "feature_distribution_drift",
    "symbol_universe_drift",
    "macro_regime_drift",
    "prediction_confidence_drift",
    "approval_rejection_mix_drift",
    "pnl_attribution_drift",
    "fill_quality_drift",
)

ENV_KILL_SWITCH_DEFAULTS = {
    "ML_PLATFORM_ENABLED": "false",
    "ML_PREDICTION_PROVIDER_ENABLED": "false",
    "ML_STATUS_EXPOSURE_ENABLED": "false",
    "ML_MODEL_ID": "",
    "ML_MODEL_MAX_AGE_SECONDS": "",
    "POLICY_ARTIFACTS_ENABLED": "true",
    "AFTER_CLOSE_POLICY_ARTIFACTS_ENABLED": "true",
}

MODEL_CARD_NON_AUTHORITY = (
    "This model does not place orders.",
    "This model does not override hard risk controls.",
    "This model does not increase position size unless explicitly promoted later.",
    "This model is invalid outside listed symbols, regimes, and date ranges.",
    "This model must abstain on stale or missing features.",
)

KNOWN_BAD_CASE_FIXTURES = (
    "suspect_quote_excessive_spread",
    "late_entry",
    "sell_to_buy_churn",
    "macro_cap_full",
    "affordability_rejection",
    "price_sanity_failure",
    "earnings_hard_avoid",
    "missing_market_context",
    "stale_market_context",
    "synthetic_matched_exit",
    "broker_fill_mismatch",
)

COUNTERFACTUAL_POLICY = {
    "problem": "Approved trades have observed outcomes, but rejected signals do not unless forward outcomes are reconstructed.",
    "selection_bias": "A supervised model trained only on approved trades learns what past approvals looked like, not which signals were worth taking.",
    "required_before_training": (
        "reconstruct rejected-signal forward returns from point-in-time bar data",
        "or explicitly mark reports as approved-trade-only and selection-biased",
    ),
    "preferred_targets": REJECTED_SIGNAL_FORWARD_RETURNS,
}

LABEL_FEEDBACK_POLICY = {
    "problem": "Realized trade labels depend on adaptive exit logic that can change over time.",
    "required_before_training": (
        "prefer fixed-horizon labels such as profit_after_15m, profit_after_30m, profit_after_60m",
        "version any realized-exit labels with exit_policy_version and position_manager_version",
        "do not mix realized PnL labels across exit-policy versions without controls",
    ),
}

VALIDATION_SPLIT_POLICY = {
    "method": "purged_walk_forward_validation",
    "requirements": (
        "purge temporally adjacent training samples near each test boundary",
        "embargo same-symbol samples immediately after training windows",
        "report symbol/date leakage checks",
        "consider combinatorial purged cross-validation for mature datasets",
    ),
}

POST_QA_SYMBOL_CANDIDATES = (
    "AMZN",
    "JPM",
    "TSM",
    "PYPL",
    "SOFI",
    "PFE",
    "CMCSA",
    "T",
    "VZ",
    "F",
    "HBAN",
    "KEY",
    "KHC",
)

SYMBOL_COHORTS = {
    "large_cap_liquid": (
        "AMZN",
        "JPM",
        "TSM",
    ),
    "defensive_dividend": (
        "T",
        "VZ",
        "PFE",
        "KHC",
        "CMCSA",
    ),
    "low_price_higher_volatility": (
        "SOFI",
        "HBAN",
        "KEY",
        "F",
    ),
}

SYMBOL_UNIVERSE_POLICY = {
    "problem": "A current fixed symbol list can introduce survivorship bias if historical membership changed.",
    "required_fields": (
        "symbol_universe_version",
        "symbol_active_from",
        "symbol_active_to",
        "symbol_add_remove_reason",
    ),
    "training_rule": "Datasets should use the symbol universe that was active at the evaluated timestamp.",
    "post_qa_candidate_symbols": POST_QA_SYMBOL_CANDIDATES,
    "post_qa_candidate_cohorts": SYMBOL_COHORTS,
    "candidate_rule": "Candidate additions require post-QA review, point-in-time universe versioning, and fresh data collection before training claims.",
    "similarity_rule": "Experience/similarity matching should compare within symbol cohorts or use normalized features before cross-cohort claims.",
    "feature_distribution_rule": "Profile feature distributions per symbol_universe_version and cohort before cross-symbol training.",
    "cohort_consistency_rule": "Treat cohort labels as hypotheses. Check whether each symbol's realized feature distributions remain cohort-consistent by regime before cross-symbol training.",
    "candidate_signal_triage_rule": "Before ML research investment, compare candidate signal frequency and signal quality against the existing approved universe.",
    "defensive_cohort_warning": "Defensive/dividend candidates may produce too few clean momentum alerts for this bot and can remain candidates indefinitely if signal quality is weak.",
}

DEMOTION_POLICY = {
    "demotion_paths": {
        "paper_gate": "observe_only",
        "warn_only": "observe_only",
        "observe_only": "research",
    },
    "triggers": (
        "rolling performance below threshold",
        "calibration drift outside tolerance",
        "feature or regime drift outside tolerance",
        "fill quality degradation",
        "operator concern or failed readiness check",
    ),
    "rule": "Promotion without a matching demotion path is incomplete.",
}

POINT_IN_TIME_CONTEXT_POLICY = {
    "problem": "Historical replay must not read the current market_context.json or current override files.",
    "required_sources": (
        "archived market_context snapshot by timestamp/date",
        "archived daily_symbol_context rows",
        "archived symbol/manual override state by effective timestamp",
        "decision_snapshot context values",
    ),
    "blocked_until": "strategy.trade_scorer and brain feature replay have point-in-time context injection.",
}

CLASS_IMBALANCE_POLICY = {
    "problem": "Accuracy can be misleading when win/loss, approve/reject, or avoid/take labels are imbalanced.",
    "required_metrics": (
        "precision_at_threshold",
        "recall_of_winners",
        "false_reject_rate_for_winners",
        "expected_value_after_friction",
        "balanced_accuracy",
        "class_distribution",
    ),
    "allowed_controls": (
        "class_weighting",
        "threshold_tuning",
        "cost-sensitive evaluation",
    ),
}

SERVING_LATENCY_CONTRACT = {
    "prediction_read_budget_ms": 25,
    "hard_timeout_ms": 50,
    "cache_or_ttl_required_before_app_integration": True,
    "cache_strategy": "in_memory_ttl_cache_loaded_outside_webhook_path",
    "ttl_seconds": 60,
    "failure_behavior": "fail_open_to_no_prediction",
    "runtime_rule": "Prediction reads must never block signal processing or hard risk checks.",
}

OVERRIDE_CONFOUNDER_POLICY = {
    "files": (
        "manual_strategy_overrides.json",
        "symbol_overrides.json",
    ),
    "required_training_fields": (
        "override_state",
        "override_source",
        "override_effective_at",
        "override_expires_at",
        "override_state_hash",
        "override_tracking_status",
    ),
    "dataset_manifest_fields": (
        "override_files",
        "override_state_hash",
        "override_tracking_status",
    ),
    "rule": "Rows affected by unknown override state must be excluded or flagged before training.",
}

POLICY_ARTIFACT_FILES = (
    "strategy_memory.json",
    "portfolio_replacement_memory.json",
    "excursion_memory.json",
    "missed_opportunity_memory.json",
    "policy_backtest_summary.json",
)

POLICY_ARTIFACT_GOVERNANCE = {
    "artifact_type": "policy_artifact",
    "problem": "After-close learning artifacts already influence runtime decisions outside the ML promotion ladder.",
    "files": POLICY_ARTIFACT_FILES,
    "runtime_loaders": (
        "strategy_memory.py",
        "portfolio_replacement_memory.py",
        "decision_policy.py",
        "decision_context.py",
    ),
    "required_manifest_fields": (
        "policy_artifact_files",
        "policy_artifact_state_hash",
        "policy_artifact_registry_hash",
        "policy_artifact_known_good_id",
        "policy_artifact_tracking_status",
    ),
    "required_status_fields": (
        "sha256",
        "mtime",
        "generated_at",
        "exists",
        "runtime_effect",
    ),
    "required_controls": (
        "hash/version visible in /status",
        "failure alert from run_after_close_learning.sh",
        "atomic temp-file plus os.replace writes",
        "rollback path to prior known-good artifact set",
        "registry entries as policy_artifact before broader ML promotion",
    ),
    "kill_switch_rule": "POLICY_ARTIFACTS_ENABLED=false makes loaders return neutral/no learned policy influence without deleting files.",
}

RETRAINING_POLICY = {
    "default_mode": "manual_reviewed_batch_retraining",
    "default_cadence": "no automatic retraining; review after 20 trading sessions or after drift/performance alert",
    "model_card_fields": (
        "last_trained_date",
        "retraining_policy",
        "retraining_trigger",
        "training_data_end_date",
        "next_retraining_review_after",
    ),
    "triggers": (
        "rolling performance decay",
        "feature distribution drift",
        "symbol universe drift",
        "macro regime shift",
        "approval/rejection mix drift",
        "scheduled after-close learning review",
    ),
}

APP_REFACTOR_RISK_POLICY = {
    "classification": "mini_project",
    "estimated_scope": "multi_week_regression_risk",
    "requirements": (
        "extract behind tests",
        "feature-flag or shadow-run new path",
        "preserve old path until behavior parity is proven",
        "avoid broker/order behavior changes during extraction",
    ),
}

DATA_RETENTION_POLICY = {
    "problem": "Decision snapshots, context history, override history, and rejected-signal outcomes can grow trades.db without bound.",
    "tiers": {
        "hot": {
            "description": "queried in webhook/status paths",
            "examples": (
                "open positions",
                "cooldowns",
                "recent sells",
                "latest market context",
                "latest policy artifact hashes",
            ),
            "storage": "trades.db or small JSON files",
        },
        "warm": {
            "description": "queried by daily ops and evaluation reports",
            "examples": (
                "recent trades",
                "feature_snapshots",
                "labeled_setups",
                "daily_symbol_context",
                "daily_symbol_events",
                "daily_symbol_predictions",
            ),
            "storage": "trades.db until growth requires partitions",
        },
        "cold": {
            "description": "archival/replay only",
            "examples": (
                "old decision snapshots",
                "old market context snapshots",
                "override history",
                "rejected-signal forward outcomes",
                "old policy artifact versions",
            ),
            "storage": "archive files or separate SQLite databases",
        },
    },
    "rule": "Classify new ML tables as hot, warm, or cold before adding them to trades.db.",
}


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    created_at: str
    source_db_path: str
    source_db_hash: str | None
    query_version: str
    label_version: str
    feature_version: str
    row_count: int
    symbol_count: int
    date_range: dict[str, str | None]
    excluded_rows_reason_counts: dict[str, int] = field(default_factory=dict)
    git_sha: str | None = None
    override_files: dict[str, str | None] = field(default_factory=dict)
    override_state_hash: str | None = None
    override_tracking_status: str = "not_tracked"
    policy_artifact_files: dict[str, str | None] = field(default_factory=dict)
    policy_artifact_state_hash: str | None = None
    policy_artifact_registry_hash: str | None = None
    policy_artifact_known_good_id: str | None = None
    policy_artifact_tracking_status: str = "not_tracked"
    pit_archive_coverage_status: str = "not_checked"
    pit_archive_per_date: dict[str, str | None] = field(default_factory=dict)
    pit_archive_missing_dates: list[str] = field(default_factory=list)
    pit_archive_fallback_dates: list[str] = field(default_factory=list)
    pit_archive_dates_without_full_artifacts: list[str] = field(default_factory=list)
    pit_archive_coverage_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
    except Exception:
        return None


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _override_file_hashes(project_root: Path) -> dict[str, str | None]:
    return {
        name: _file_sha256(project_root / name)
        for name in OVERRIDE_CONFOUNDER_POLICY["files"]
    }


def _policy_artifact_hashes(project_root: Path) -> dict[str, str | None]:
    return {
        name: _file_sha256(project_root / name)
        for name in POLICY_ARTIFACT_FILES
    }


def _policy_artifact_registry_hash(project_root: Path) -> str | None:
    return _file_sha256(project_root / "data_archive" / "policy_artifacts" / "registry.json")


def _policy_artifact_known_good_id(project_root: Path) -> str | None:
    path = project_root / "data_archive" / "policy_artifacts" / "known_good.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            value = data.get("artifact_set_id")
            return str(value) if value else None
    except Exception:
        return None
    return None


def build_dataset_manifest(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    query_version: str = "brain_features_query_v1",
    label_version: str = "label_taxonomy_v1",
    feature_version: str = FEATURE_VERSION,
    excluded_rows_reason_counts: dict[str, int] | None = None,
    pit_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only dataset manifest from current source DB metadata."""
    db_path = Path(db_path)
    source_summary = TrainingDataRepository(db_path).manifest_source_summary(
        start_date,
        end_date,
    )
    row_count = source_summary["row_count"]
    symbol_count = source_summary["symbol_count"]
    date_range = source_summary["date_range"]

    created_at = datetime.now(timezone.utc).isoformat()
    source_db_hash = _file_sha256(db_path)
    git_sha = _git_sha()
    project_root = Path(__file__).resolve().parents[1]
    override_files = _override_file_hashes(project_root)
    override_state_hash = hashlib.sha256(
        json.dumps(override_files, sort_keys=True).encode("utf-8")
    ).hexdigest()
    override_tracking_status = (
        "hashed_current_files_only"
        if any(value is not None for value in override_files.values())
        else "no_override_files_present"
    )
    policy_artifact_files = _policy_artifact_hashes(project_root)
    policy_artifact_state_hash = hashlib.sha256(
        json.dumps(policy_artifact_files, sort_keys=True).encode("utf-8")
    ).hexdigest()
    policy_artifact_registry_hash = _policy_artifact_registry_hash(project_root)
    policy_artifact_known_good_id = _policy_artifact_known_good_id(project_root)
    policy_artifact_tracking_status = (
        "registry_and_current_files_hashed"
        if policy_artifact_registry_hash
        else "hashed_current_files_only"
        if any(value is not None for value in policy_artifact_files.values())
        else "no_policy_artifacts_present"
    )
    identity_payload = {
        "source_db_hash": source_db_hash,
        "query_version": query_version,
        "label_version": label_version,
        "feature_version": feature_version,
        "row_count": row_count,
        "symbol_count": symbol_count,
        "date_range": date_range,
        "git_sha": git_sha,
        "override_state_hash": override_state_hash,
        "override_tracking_status": override_tracking_status,
        "policy_artifact_state_hash": policy_artifact_state_hash,
        "policy_artifact_registry_hash": policy_artifact_registry_hash,
        "policy_artifact_known_good_id": policy_artifact_known_good_id,
        "policy_artifact_tracking_status": policy_artifact_tracking_status,
    }
    dataset_id = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    manifest = DatasetManifest(
        dataset_id=dataset_id,
        created_at=created_at,
        source_db_path=str(db_path),
        source_db_hash=source_db_hash,
        query_version=query_version,
        label_version=label_version,
        feature_version=feature_version,
        row_count=row_count,
        symbol_count=symbol_count,
        date_range=date_range,
        excluded_rows_reason_counts=excluded_rows_reason_counts or {},
        git_sha=git_sha,
        override_files=override_files,
        override_state_hash=override_state_hash,
        override_tracking_status=override_tracking_status,
        policy_artifact_files=policy_artifact_files,
        policy_artifact_state_hash=policy_artifact_state_hash,
        policy_artifact_registry_hash=policy_artifact_registry_hash,
        policy_artifact_known_good_id=policy_artifact_known_good_id,
        policy_artifact_tracking_status=policy_artifact_tracking_status,
        pit_archive_coverage_status=(pit_coverage or {}).get("status", "not_checked"),
        pit_archive_per_date=(pit_coverage or {}).get("per_date", {}),
        pit_archive_missing_dates=(pit_coverage or {}).get("missing_dates", []),
        pit_archive_fallback_dates=(pit_coverage or {}).get("fallback_dates", []),
        pit_archive_dates_without_full_artifacts=(pit_coverage or {}).get(
            "dates_without_full_policy_artifacts", []
        ),
        pit_archive_coverage_pct=(pit_coverage or {}).get("coverage_pct"),
    )
    return manifest.to_dict()


def label_taxonomy() -> dict[str, Any]:
    return LABEL_TAXONOMY_V1


def model_card_template(model_id: str = "candidate_model") -> dict[str, Any]:
    return {
        "model_id": model_id,
        "status": "research",
        "artifact_path": None,
        "dataset_manifest_id": None,
        "feature_version": FEATURE_VERSION,
        "label_version": LABEL_TAXONOMY_V1["version"],
        "training_window": None,
        "validation_window": None,
        "supported_symbols": [],
        "supported_regimes": [],
        "known_invalid_conditions": [
            "stale features",
            "missing decision snapshot",
            "outside validation date range",
            "point-in-time context unavailable",
            "unsupported symbol universe version",
        ],
        "minimum_sample_gates": MIN_SAMPLE_GATES,
        "calibration_required": True,
        "rollback_plan": None,
        "demotion_policy": DEMOTION_POLICY,
        "last_trained_date": None,
        "retraining_policy": RETRAINING_POLICY["default_mode"],
        "next_retraining_review_after": None,
        "non_authority": MODEL_CARD_NON_AUTHORITY,
    }


def governance_contract() -> dict[str, Any]:
    return {
        "data_leakage_policy": LEAKAGE_POLICY,
        "decision_snapshot_required_fields": DECISION_SNAPSHOT_FIELDS,
        "dataset_manifest_required_fields": tuple(DatasetManifest.__dataclass_fields__.keys()),
        "label_taxonomy": LABEL_TAXONOMY_V1,
        "rejected_signal_forward_returns": REJECTED_SIGNAL_FORWARD_RETURNS,
        "order_fill_truth_hierarchy": ORDER_FILL_TRUTH_HIERARCHY,
        "fill_confidence_values": FILL_CONFIDENCE_VALUES,
        "model_output_contract": MODEL_OUTPUT_CONTRACT,
        "minimum_sample_gates": MIN_SAMPLE_GATES,
        "baseline_policies": BASELINE_POLICIES,
        "friction_assumptions": FRICTION_ASSUMPTIONS,
        "calibration_buckets": CALIBRATION_BUCKETS,
        "drift_checks": DRIFT_CHECKS,
        "env_kill_switch_defaults": ENV_KILL_SWITCH_DEFAULTS,
        "model_card_non_authority": MODEL_CARD_NON_AUTHORITY,
        "known_bad_case_fixtures": KNOWN_BAD_CASE_FIXTURES,
        "policy_artifact_governance": POLICY_ARTIFACT_GOVERNANCE,
        "counterfactual_policy": COUNTERFACTUAL_POLICY,
        "label_feedback_policy": LABEL_FEEDBACK_POLICY,
        "validation_split_policy": VALIDATION_SPLIT_POLICY,
        "post_qa_symbol_candidates": POST_QA_SYMBOL_CANDIDATES,
        "symbol_cohorts": SYMBOL_COHORTS,
        "symbol_universe_policy": SYMBOL_UNIVERSE_POLICY,
        "demotion_policy": DEMOTION_POLICY,
        "point_in_time_context_policy": POINT_IN_TIME_CONTEXT_POLICY,
        "class_imbalance_policy": CLASS_IMBALANCE_POLICY,
        "serving_latency_contract": SERVING_LATENCY_CONTRACT,
        "override_confounder_policy": OVERRIDE_CONFOUNDER_POLICY,
        "retraining_policy": RETRAINING_POLICY,
        "app_refactor_risk_policy": APP_REFACTOR_RISK_POLICY,
        "data_retention_policy": DATA_RETENTION_POLICY,
    }
