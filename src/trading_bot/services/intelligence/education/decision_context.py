"""Education concept context for decision explanations.

This module intentionally does not read the education database and does not
make approval, sizing, or execution decisions. It maps already-built runtime
context into relevant education concepts so AI/review layers can explain what
kind of learned reference material applies to the current situation.
"""

from __future__ import annotations

from typing import Any

from services.intelligence.education.corpus import CURATED_TRADING_EDUCATION_CONCEPTS

EDUCATION_DECISION_CONTEXT_VERSION = "trading_education_decision_context_v1"
EDUCATION_DECISION_RUNTIME_EFFECT = "education_advisory_context_no_direct_authority"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, dict):
            parts.extend(str(v) for v in value.values() if v is not None)
        elif isinstance(value, (list, tuple, set)):
            parts.extend(str(v) for v in value if v is not None)
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts).lower()


def _concept_lookup() -> dict[str, dict[str, Any]]:
    return {concept.key: concept.to_dict() for concept in CURATED_TRADING_EDUCATION_CONCEPTS}


def _add(
    rows: list[dict[str, Any]],
    lookup: dict[str, dict[str, Any]],
    key: str,
    *,
    relevance: str,
    evidence: str,
    influence_policy: str,
) -> None:
    concept = lookup.get(key)
    if not concept:
        return
    if any(row["key"] == key for row in rows):
        return
    rows.append(
        {
            "key": key,
            "name": concept["name"],
            "concept_type": concept["concept_type"],
            "relevance": relevance,
            "evidence": evidence,
            "influence_policy": influence_policy,
            "related_features": concept["related_features"][:8],
            "guardrails": concept["guardrails"][:3],
        }
    )


def education_context_for_account_state(
    account_state: dict[str, Any] | None,
    *,
    action: str | None = None,
    max_concepts: int = 5,
) -> dict[str, Any]:
    """Return relevant education concepts for the already-built runtime state."""

    state = _dict(account_state)
    action_s = str(action or state.get("action") or "").lower()
    lookup = _concept_lookup()
    rows: list[dict[str, Any]] = []

    event_context = _dict(state.get("event_context"))
    setup_quality = _dict(state.get("setup_quality") or state.get("setup_observation"))
    momentum = _dict(state.get("momentum") or state.get("rolling_momentum"))
    session = _dict(state.get("session_momentum"))
    prediction = _dict(state.get("prediction_gate") or state.get("ml_prediction"))
    volatility = _dict(state.get("volatility_normalization") or state.get("volatility_inputs"))
    exit_quality = _dict(state.get("exit_decision_quality"))
    market_microstructure = _dict(state.get("market_microstructure"))

    event_blob = _text_blob(event_context)
    if event_blob and any(
        term in event_blob
        for term in ("earnings", "guidance", "headline", "priced", "sell the news", "event")
    ):
        _add(
            rows,
            lookup,
            "news_expectations_positioning",
            relevance="event interpretation",
            evidence="event context references headlines, expectations, guidance, or priced-in behavior",
            influence_policy="may inform explanation and confidence framing; requires source confirmation",
        )
    if any(term in event_blob for term in ("ipo", "s-1", "lock-up", "lockup", "blackout")):
        _add(
            rows,
            lookup,
            "ipo_liquidity_restrictions",
            relevance="event risk",
            evidence="event context references IPO, S-1, lock-up, blackout, or trading-window mechanics",
            influence_policy="may inform event-risk explanation; official filings remain source of truth",
        )

    setup_blob = _text_blob(setup_quality, market_microstructure)
    if any(term in setup_blob for term in ("breakout", "opening_range", "new_high")):
        _add(
            rows,
            lookup,
            "breakout_trading",
            relevance="setup structure",
            evidence="setup or microstructure context references breakout behavior",
            influence_policy="may inform setup explanation; does not approve breakout trades by itself",
        )
    if any(term in setup_blob for term in ("reversal", "pullback", "retest", "trend_break")):
        _add(
            rows,
            lookup,
            "reversal_trading",
            relevance="setup structure",
            evidence="setup context references reversal, pullback, retest, or trend-break behavior",
            influence_policy="may inform setup explanation; requires outcome evidence before authority",
        )

    momentum_blob = _text_blob(momentum, session, exit_quality)
    if any(
        term in momentum_blob
        for term in ("falling", "deteriorat", "parabolic", "close_near_low", "exit_pressure")
    ) or (action_s == "sell" and momentum_blob):
        _add(
            rows,
            lookup,
            "rally_exhaustion_exit_patterns",
            relevance="exit review",
            evidence="momentum or exit context indicates deterioration, exhaustion, or sell review",
            influence_policy="may inform sell explanation and review; no standalone exit authority",
        )
    if any(term in momentum_blob for term in ("force", "pvt", "efi", "accelerating", "rising")):
        _add(
            rows,
            lookup,
            "momentum_trading",
            relevance="momentum context",
            evidence="momentum context references force, PVT/EFI, acceleration, or rising direction",
            influence_policy="may inform opportunity explanation; calibrated outcome evidence required",
        )

    volatility_blob = _text_blob(volatility, event_context)
    if any(
        term in volatility_blob for term in ("implied", "iv_", "vix", "expected_move", "tail_risk")
    ):
        _add(
            rows,
            lookup,
            "implied_volatility_context",
            relevance="volatility/event risk",
            evidence="volatility context references IV, VIX, expected move, or tail risk",
            influence_policy="may inform risk explanation; IV alone does not imply direction",
        )

    prediction_blob = _text_blob(prediction)
    if prediction_blob:
        _add(
            rows,
            lookup,
            "algorithmic_trading_pipeline",
            relevance="model governance",
            evidence="prediction context is present in account state",
            influence_policy="may inform model-readiness explanation; promotion gates control authority",
        )

    limited = rows[: max(0, int(max_concepts))]
    return {
        "version": EDUCATION_DECISION_CONTEXT_VERSION,
        "runtime_effect": EDUCATION_DECISION_RUNTIME_EFFECT,
        "concept_count": len(limited),
        "concepts": limited,
        "authority_note": (
            "Education context can shape AI explanation and operator review, but cannot directly "
            "approve, block, size, or execute trades without explicit promoted policy wiring."
        ),
    }
