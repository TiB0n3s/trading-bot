"""Advanced-alpha feature definitions."""

from __future__ import annotations

from .registry_types import FeatureSpec

ADVANCED_ALPHA_V1_FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="cumulative_volume_delta",
        dtype="float",
        nullable=True,
        default=None,
        runtime_source="bar_pattern_features.cumulative_volume_delta",
        offline_source="bar_pattern_features.cumulative_volume_delta",
        point_in_time_cutoff="bar_interval_close <= decision_time",
        staleness_rule="same session cumulative state",
        semantic_version="advanced_alpha_v1",
        authority_eligibility="paper_only_after_lifecycle",
    ),
    FeatureSpec(
        name="fractional_diff_zscore_20",
        dtype="float",
        nullable=True,
        default=None,
        runtime_source="bar_pattern_features.fractional_diff_zscore_20",
        offline_source="bar_pattern_features.fractional_diff_zscore_20",
        point_in_time_cutoff="bar_interval_close <= decision_time",
        staleness_rule="rolling window available and not stale",
        semantic_version="advanced_alpha_v1",
        authority_eligibility="paper_only_after_lifecycle",
    ),
    FeatureSpec(
        name="liquidity_stress_indicator",
        dtype="float",
        nullable=True,
        default=None,
        runtime_source="sizing_policy/liquidity stress context",
        offline_source="execution_quality plus bar order-flow proxy features",
        point_in_time_cutoff="decision_time_or_earlier",
        staleness_rule="execution quality snapshot not stale",
        semantic_version="advanced_alpha_v1",
        authority_eligibility="size_down_only_after_lifecycle",
    ),
)
