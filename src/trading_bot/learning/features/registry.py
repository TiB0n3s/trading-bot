"""Single versioned feature registry for learning surfaces."""

from __future__ import annotations

from typing import Any

from .advanced_alpha_v1 import ADVANCED_ALPHA_V1_FEATURES
from .bar_pattern_v1 import BAR_PATTERN_V1_FEATURES
from .decision_v4 import DECISION_V4_FEATURES
from .registry_types import FeatureSpec

FEATURE_REGISTRY_VERSION = "learning_feature_registry_v1"


def all_feature_specs() -> tuple[FeatureSpec, ...]:
    return (
        *DECISION_V4_FEATURES,
        *BAR_PATTERN_V1_FEATURES,
        *ADVANCED_ALPHA_V1_FEATURES,
    )


def feature_registry_summary() -> dict[str, Any]:
    features = all_feature_specs()
    return {
        "report_version": FEATURE_REGISTRY_VERSION,
        "feature_count": len(features),
        "semantic_versions": sorted({row.semantic_version for row in features}),
        "authority_eligibility": sorted({row.authority_eligibility for row in features}),
        "features": [row.to_dict() for row in features],
    }
