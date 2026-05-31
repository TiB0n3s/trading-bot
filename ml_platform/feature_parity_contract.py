"""Runtime/offline feature parity contract for ML-facing decision features.

The contract is intentionally metadata-only. It identifies live decision
features that are also exported for offline ML and documents the required
runtime snapshot field, null semantics, and point-in-time cutoff rule.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ml_platform.dataset_builder import ROW_COLUMNS
from services.decision_snapshot_service import (
    DECISION_SNAPSHOT_FEATURE_SEMANTIC_VERSION,
    SNAPSHOT_CONTEXT_FIELDS,
)


@dataclass(frozen=True)
class FeatureParitySpec:
    field: str
    runtime_snapshot_field: str
    offline_export_field: str
    null_semantics: str
    point_in_time_cutoff: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


DECISION_SNAPSHOT_ROW_FIELDS = (
    "setup_label",
    "setup_confidence",
    "setup_score",
    "prediction_score",
    "prediction_confidence",
    "prediction_sample_size",
)


RUNTIME_SNAPSHOT_FEATURE_FIELDS = tuple(
    dict.fromkeys((*SNAPSHOT_CONTEXT_FIELDS, *DECISION_SNAPSHOT_ROW_FIELDS))
)


LIVE_DECISION_ML_FEATURE_PARITY: tuple[FeatureParitySpec, ...] = (
    FeatureParitySpec(
        field="macro_regime",
        runtime_snapshot_field="macro_regime",
        offline_export_field="macro_regime",
        null_semantics="nullable; missing value means macro context unavailable at decision time",
        point_in_time_cutoff="decision_time_or_earlier",
        source="runtime macro/context state",
    ),
    FeatureParitySpec(
        field="market_bias",
        runtime_snapshot_field="market_bias",
        offline_export_field="market_bias",
        null_semantics="nullable; missing value means no same-day market context was available",
        point_in_time_cutoff="decision_time_or_earlier",
        source="market_context.json loaded for expected market date",
    ),
    FeatureParitySpec(
        field="trend_direction",
        runtime_snapshot_field="trend_direction",
        offline_export_field="trend_direction",
        null_semantics="nullable; missing value means trend table did not have usable history",
        point_in_time_cutoff="decision_time_or_earlier",
        source="trend state built from prior signal/order history",
    ),
    FeatureParitySpec(
        field="trend_strength",
        runtime_snapshot_field="trend_strength",
        offline_export_field="trend_strength",
        null_semantics="nullable; missing value means trend table did not have usable history",
        point_in_time_cutoff="decision_time_or_earlier",
        source="trend state built from prior signal/order history",
    ),
    FeatureParitySpec(
        field="setup_label",
        runtime_snapshot_field="setup_label",
        offline_export_field="setup_label",
        null_semantics="nullable; null means setup classification unavailable or degraded at decision time",
        point_in_time_cutoff="decision_time_or_earlier",
        source="setup observation from live feature snapshot",
    ),
    FeatureParitySpec(
        field="setup_score",
        runtime_snapshot_field="setup_score",
        offline_export_field="setup_score",
        null_semantics="nullable numeric; null means setup score unavailable or degraded",
        point_in_time_cutoff="decision_time_or_earlier",
        source="setup observation from live feature snapshot",
    ),
    FeatureParitySpec(
        field="setup_confidence",
        runtime_snapshot_field="setup_confidence",
        offline_export_field="setup_confidence",
        null_semantics="nullable; null means setup confidence unavailable or degraded",
        point_in_time_cutoff="decision_time_or_earlier",
        source="setup observation from live feature snapshot",
    ),
    FeatureParitySpec(
        field="prediction_score",
        runtime_snapshot_field="prediction_score",
        offline_export_field="prediction_score",
        null_semantics="nullable numeric; null means no observe-only prediction was available",
        point_in_time_cutoff="prediction_cache_loaded_for_market_date_at_or_before_decision_time",
        source="daily_symbol_predictions observe-only cache",
    ),
    FeatureParitySpec(
        field="prediction_confidence",
        runtime_snapshot_field="prediction_confidence",
        offline_export_field="prediction_confidence",
        null_semantics="nullable; null means no observe-only prediction confidence was available",
        point_in_time_cutoff="prediction_cache_loaded_for_market_date_at_or_before_decision_time",
        source="daily_symbol_predictions observe-only cache",
    ),
    FeatureParitySpec(
        field="prediction_sample_size",
        runtime_snapshot_field="prediction_sample_size",
        offline_export_field="prediction_sample_size",
        null_semantics="nullable integer; null means no observe-only prediction sample size was available",
        point_in_time_cutoff="prediction_cache_loaded_for_market_date_at_or_before_decision_time",
        source="daily_symbol_predictions observe-only cache",
    ),
)


def parity_contract_summary() -> dict:
    return {
        "contract_name": "runtime_offline_feature_parity_v1",
        "runtime_feature_semantic_version": DECISION_SNAPSHOT_FEATURE_SEMANTIC_VERSION,
        "runtime_snapshot": "decision_snapshots",
        "offline_export": "ml_platform.dataset_builder.ROW_COLUMNS",
        "features": [spec.to_dict() for spec in LIVE_DECISION_ML_FEATURE_PARITY],
        "offline_columns": list(ROW_COLUMNS),
        "runtime_snapshot_fields": list(RUNTIME_SNAPSHOT_FEATURE_FIELDS),
    }
