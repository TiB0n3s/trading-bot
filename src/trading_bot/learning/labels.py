"""Explicit label hierarchy and authority rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

LABEL_HIERARCHY_VERSION = "label_hierarchy_v1"


@dataclass(frozen=True)
class LabelTier:
    tier: int
    key: str
    labels: tuple[str, ...]
    allowed_authority: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


LABEL_TIERS: tuple[LabelTier, ...] = (
    LabelTier(
        tier=1,
        key="realized_trade_outcomes",
        labels=("realized_pnl", "realized_pnl_pct", "net_outcome_after_costs"),
        allowed_authority="narrow_block_candidate_after_full_lifecycle",
        description="Broker-confirmed net outcomes after fills, exits, and costs.",
    ),
    LabelTier(
        tier=2,
        key="matched_trade_lifecycle",
        labels=("matched_trade_outcome", "mfe", "mae", "exit_reason"),
        allowed_authority="size_down_candidate_after_full_lifecycle",
        description="Reconstructed lifecycle outcomes with entry/exit linkage.",
    ),
    LabelTier(
        tier=3,
        key="rejected_signal_counterfactual",
        labels=("return_15m", "return_60m", "max_favorable_60m", "max_adverse_60m"),
        allowed_authority="paper_only_candidate_review",
        description="Counterfactual rejected-signal outcomes.",
    ),
    LabelTier(
        tier=4,
        key="fixed_horizon_movement",
        labels=(
            "ret_fwd_5m",
            "ret_fwd_15m",
            "ret_fwd_30m",
            "triple_barrier_label",
            "trend_scan_label",
        ),
        allowed_authority="observe_only_ranking",
        description="Forward movement/proxy labels; useful for ranking, not direct authority.",
    ),
    LabelTier(
        tier=5,
        key="diagnostic_regime",
        labels=("regime_label", "toxicity_bucket", "session_phase"),
        allowed_authority="diagnostic_only",
        description="Diagnostic context labels for segmentation and stability reporting.",
    ),
)


def label_hierarchy_summary() -> dict[str, Any]:
    return {
        "report_version": LABEL_HIERARCHY_VERSION,
        "tiers": [tier.to_dict() for tier in LABEL_TIERS],
        "rule": (
            "A model may not receive more authority than its weakest primary "
            "training label tier supports."
        ),
    }


def authority_for_label(label_name: str) -> str:
    label_name = str(label_name or "")
    for tier in LABEL_TIERS:
        if label_name in tier.labels:
            return tier.allowed_authority
    return "unknown_label_observe_only"


_LABEL_TO_TIER: dict[str, int] = {
    label: tier.tier for tier in LABEL_TIERS for label in tier.labels
}

# Paper meta-label trade authority (veto / approve / size) requires the model's
# WEAKEST primary training label to be Tier <= 3 (paper_only_candidate_review).
# Tier 4+ (observe_only_ranking / diagnostic_only) grant ranking/observation
# only, never trade authority. Enforces the label-hierarchy rule in code, not
# just documentation.
META_LABEL_AUTHORITY_MIN_TIER = 3

# Labels the historical-bar ensemble actually trains on today (all Tier 4),
# used as the default when a caller does not declare its training labels.
DEFAULT_HISTORICAL_BAR_TRAINING_LABELS: tuple[str, ...] = (
    "triple_barrier_label",
    "trend_scan_label",
)


def tier_for_label(label_name: str) -> int:
    """Return the tier number for a label (higher = weaker; 99 = unknown)."""
    return _LABEL_TO_TIER.get(str(label_name or ""), 99)


def labels_support_meta_label_authority(label_names: Any) -> bool:
    """True only if EVERY training label is Tier <= META_LABEL_AUTHORITY_MIN_TIER.

    A single Tier-4+ (observe-only / diagnostic) label restricts the model to
    ranking/observation, so it may not veto, approve, or size a trade.
    """
    labels = [str(x) for x in (label_names or []) if str(x)]
    if not labels:
        return False
    weakest_tier = max(tier_for_label(name) for name in labels)
    return weakest_tier <= META_LABEL_AUTHORITY_MIN_TIER
