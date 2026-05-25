"""Governance contracts for ML research and promotion.

This module is intentionally declarative and read-only. It defines the audit,
leakage, label, manifest, and promotion rules that future ML code must satisfy
before any runtime integration is considered.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import DB_PATH
from ml_platform.config import FEATURE_VERSION


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
    "labels": (
        "entry_quality_outcome",
        "max_favorable_excursion",
        "max_adverse_excursion",
        "time_to_profit",
        "time_to_drawdown",
        "profit_after_15m",
        "profit_after_30m",
        "profit_after_60m",
        "would_hit_stop",
        "would_hit_take_profit",
        "was_late_entry",
        "was_churn",
        "was_bad_fill",
        "was_correct_rejection",
    ),
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
    "current_bot_policy",
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


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def build_dataset_manifest(
    *,
    db_path: Path | str = DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    query_version: str = "brain_features_query_v1",
    label_version: str = "label_taxonomy_v1",
    feature_version: str = FEATURE_VERSION,
    excluded_rows_reason_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a read-only dataset manifest from current source DB metadata."""
    db_path = Path(db_path)
    row_count = 0
    symbol_count = 0
    date_range: dict[str, str | None] = {"start": start_date, "end": end_date}

    if db_path.exists():
        where_sql = ""
        params: tuple[str, ...] = ()
        if start_date and end_date:
            where_sql = "WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?"
            params = (start_date, end_date)
        elif start_date or end_date:
            raise ValueError("Provide both start_date and end_date, or neither")

        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            if _table_exists(con, "feature_snapshots"):
                row = con.execute(
                    f"SELECT COUNT(*) AS rows, COUNT(DISTINCT symbol) AS symbols FROM feature_snapshots {where_sql}",
                    params,
                ).fetchone()
                row_count = int(row["rows"] or 0)
                symbol_count = int(row["symbols"] or 0)
                if not start_date and not end_date:
                    range_row = con.execute(
                        "SELECT MIN(substr(timestamp, 1, 10)) AS start, MAX(substr(timestamp, 1, 10)) AS end FROM feature_snapshots"
                    ).fetchone()
                    date_range = {"start": range_row["start"], "end": range_row["end"]}

    created_at = datetime.now(timezone.utc).isoformat()
    source_db_hash = _file_sha256(db_path)
    git_sha = _git_sha()
    identity_payload = {
        "source_db_hash": source_db_hash,
        "query_version": query_version,
        "label_version": label_version,
        "feature_version": feature_version,
        "row_count": row_count,
        "symbol_count": symbol_count,
        "date_range": date_range,
        "git_sha": git_sha,
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
        ],
        "minimum_sample_gates": MIN_SAMPLE_GATES,
        "calibration_required": True,
        "rollback_plan": None,
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
    }
