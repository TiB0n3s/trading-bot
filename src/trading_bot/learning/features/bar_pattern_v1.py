"""Bar-pattern feature definitions."""

from __future__ import annotations

from .registry_types import FeatureSpec

BAR_PATTERN_V1_FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="long_opportunity_score",
        dtype="float",
        nullable=True,
        default=None,
        runtime_source="bar_pattern_features.long_opportunity_score",
        offline_source="historical_bar_archive/bar_pattern_features",
        point_in_time_cutoff="bar_interval_close <= decision_time",
        staleness_rule="current session bar or historical training row",
        semantic_version="bar_pattern_v1",
        authority_eligibility="paper_only_after_lifecycle",
    ),
    FeatureSpec(
        name="triple_barrier_label",
        dtype="int",
        nullable=True,
        default=None,
        runtime_source="not_runtime_authority_label",
        offline_source="bar_pattern_features.triple_barrier_label",
        point_in_time_cutoff="label generated only after forward horizon completes",
        staleness_rule="training_only_never_runtime_feature",
        semantic_version="bar_pattern_v1",
        authority_eligibility="training_label_only",
    ),
    FeatureSpec(
        name="trend_scan_label",
        dtype="int",
        nullable=True,
        default=None,
        runtime_source="not_runtime_authority_label",
        offline_source="bar_pattern_features.trend_scan_label",
        point_in_time_cutoff="label generated only after forward horizon completes",
        staleness_rule="training_only_never_runtime_feature",
        semantic_version="bar_pattern_v1",
        authority_eligibility="training_label_only",
    ),
    FeatureSpec(
        name="vpin_toxicity_20",
        dtype="float",
        nullable=True,
        default=None,
        runtime_source="bar_pattern_features.vpin_toxicity_20",
        offline_source="bar_pattern_features.vpin_toxicity_20",
        point_in_time_cutoff="bar_interval_close <= decision_time",
        staleness_rule="current session bar or historical training row",
        semantic_version="bar_pattern_v1",
        authority_eligibility="size_down_only_after_lifecycle",
    ),
)
