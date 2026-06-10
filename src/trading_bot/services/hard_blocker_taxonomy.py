"""Canonical hard-blocker taxonomy for decision-quality review.

This module is descriptive. It classifies existing rejection categories into a
small set of strict blocker domains so future reports can distinguish true
account/liquidity/risk constraints from softer edge-model or advisory gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

HARD_BLOCKER_TAXONOMY_VERSION = "hard_blocker_taxonomy_v1"

HARD_BLOCKER_DOMAINS = {
    "stale_signal",
    "liquidity_or_spread",
    "broker_or_account_constraint",
    "max_risk",
    "broken_market_regime",
}

_CATEGORY_DOMAIN_MAP = {
    "stale_signal": "stale_signal",
    "second_look": "liquidity_or_spread",
    "spread": "liquidity_or_spread",
    "spread_check": "liquidity_or_spread",
    "pre_order_safety": "liquidity_or_spread",
    "affordability": "broker_or_account_constraint",
    "broker_rejected": "broker_or_account_constraint",
    "broker_submit_failed": "broker_or_account_constraint",
    "order_submit_failed": "broker_or_account_constraint",
    "cash_safe": "broker_or_account_constraint",
    "daily_loss_limit": "max_risk",
    "max_risk": "max_risk",
    "macro_position_limit": "max_risk",
    "macro_risk": "broken_market_regime",
    "session_momentum_gate": "broken_market_regime",
}


@dataclass(frozen=True)
class HardBlockerClassification:
    category: str
    domain: str | None
    is_hard_blocker: bool
    reason: str | None = None
    taxonomy_version: str = HARD_BLOCKER_TAXONOMY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_hard_blocker(
    category: str | None, reason: str | None = None
) -> HardBlockerClassification:
    normalized = str(category or "").strip().lower()
    domain = _CATEGORY_DOMAIN_MAP.get(normalized)

    reason_text = str(reason or "").lower()
    if domain is None and "spread" in reason_text:
        domain = "liquidity_or_spread"
    elif domain is None and any(
        token in reason_text for token in ("buying_power", "broker", "account")
    ):
        domain = "broker_or_account_constraint"
    elif domain is None and any(
        token in reason_text for token in ("max risk", "daily loss", "risk limit")
    ):
        domain = "max_risk"

    return HardBlockerClassification(
        category=normalized or "unknown",
        domain=domain,
        is_hard_blocker=domain in HARD_BLOCKER_DOMAINS,
        reason=reason,
    )


def hard_blocker_contract() -> dict[str, Any]:
    return {
        "taxonomy_version": HARD_BLOCKER_TAXONOMY_VERSION,
        "hard_blocker_domains": sorted(HARD_BLOCKER_DOMAINS),
        "authority_note": (
            "Only these domains should remain strict binary blockers; "
            "edge-model and advisory signals should use observe-only or sizing paths."
        ),
    }
