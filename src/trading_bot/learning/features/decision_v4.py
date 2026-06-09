"""Decision snapshot v4 feature definitions."""

from __future__ import annotations

from .registry_types import FeatureSpec

DECISION_V4_FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="setup_score",
        dtype="float",
        nullable=True,
        default=None,
        runtime_source="decision_snapshots.setup_score",
        offline_source="ml_platform.dataset_builder.setup_score",
        point_in_time_cutoff="decision_time_or_earlier",
        staleness_rule="feature_age_seconds <= runtime configured max age",
        semantic_version="decision_v4",
        authority_eligibility="paper_only_after_lifecycle",
    ),
    FeatureSpec(
        name="prediction_score",
        dtype="float",
        nullable=True,
        default=None,
        runtime_source="decision_snapshots.prediction_score",
        offline_source="daily_symbol_predictions at feature_available_at",
        point_in_time_cutoff="prediction_loaded_before_decision",
        staleness_rule="same market date and cache not stale",
        semantic_version="decision_v4",
        authority_eligibility="observe_only_ranking",
    ),
    FeatureSpec(
        name="momentum_acceleration_pct",
        dtype="float",
        nullable=True,
        default=None,
        runtime_source="decision_snapshots.momentum_acceleration_pct",
        offline_source="feature_snapshots.momentum_acceleration_pct",
        point_in_time_cutoff="feature_available_at <= decision_time",
        staleness_rule="feature_age_seconds <= runtime configured max age",
        semantic_version="decision_v4",
        authority_eligibility="paper_only_after_lifecycle",
    ),
    FeatureSpec(
        name="volume_surge_ratio",
        dtype="float",
        nullable=True,
        default=None,
        runtime_source="decision_snapshots.volume_surge_ratio",
        offline_source="feature_snapshots.volume_surge_ratio",
        point_in_time_cutoff="feature_available_at <= decision_time",
        staleness_rule="feature_age_seconds <= runtime configured max age",
        semantic_version="decision_v4",
        authority_eligibility="paper_only_after_lifecycle",
    ),
)
