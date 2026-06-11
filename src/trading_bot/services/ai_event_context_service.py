"""Context-only AI interpretation for collected market events.

This service is intentionally non-authoritative. It can summarize source
evidence and clarify intent, but it cannot approve, reject, size, or alter
execution. Live collection must explicitly opt in before any LLM call is made.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

AI_EVENT_CONTEXT_VERSION = "ai_event_context_v1"
AI_EVENT_CONTEXT_AUTHORITY = "context_only_no_standalone_buy_authority"

Provider = Callable[[str], dict[str, Any] | str]
SEMANTIC_SOURCE_TIERS = {"official", "confirmed_financial_news", "deep_analysis"}
SEMANTIC_EVENT_TYPES = {
    "earnings",
    "guidance",
    "regulatory",
    "lawsuit",
    "macro_geopolitical",
    "congressional_trade_disclosure",
    "strategic_partnership",
    "mna_deal_chatter",
    "customer_contract",
    "supplier_signal",
}
SEMANTIC_IMPACTS = {
    "strongly_bullish",
    "moderately_bullish",
    "moderately_bearish",
    "strongly_bearish",
}
SEMANTIC_RELEVANCE = {"actionable", "caution", "review_required"}


@dataclass(frozen=True)
class AIEventContextConfig:
    enabled: bool = False
    provider_name: str = "disabled"
    max_summary_chars: int = 900


def build_ai_event_context_prompt(event: dict[str, Any]) -> str:
    """Build a constrained prompt for one event.

    The prompt asks for interpretation, not a trading decision. The response
    contract is JSON-only so downstream code can validate it before storing.
    """
    compact = {
        "symbol": event.get("symbol"),
        "event_type": event.get("event_type"),
        "event_summary": event.get("event_summary"),
        "source": event.get("source"),
        "source_tier": event.get("source_tier"),
        "source_url": event.get("source_url"),
        "search_scope": event.get("search_scope"),
        "context_only": event.get("context_only"),
        "linked_symbols": event.get("linked_symbols"),
        "intent_category": event.get("intent_category"),
        "intent_direction": event.get("intent_direction"),
        "intent_scope": event.get("intent_scope"),
        "confirmation_status": event.get("confirmation_status"),
        "missing_evidence": event.get("missing_evidence"),
        "expected_market_impact": event.get("expected_market_impact"),
        "trade_relevance": event.get("trade_relevance"),
        "scoring_reason": event.get("scoring_reason"),
        "information_novelty": event.get("information_novelty"),
        "positioning_effect": event.get("positioning_effect"),
        "earnings_positioning_context": event.get("earnings_positioning_context"),
        "earnings_information_surprise": event.get("earnings_information_surprise"),
    }
    return (
        "Interpret this market event for context only. Do not make a trading "
        "recommendation. Do not infer bullish authority from delayed, rumor, "
        "unconfirmed, or context-only evidence. Return JSON only with keys: "
        "summary, intent, affected_symbols, market_alignment, confidence, "
        "confirmation_status, information_novelty, positioning_effect, "
        "earnings_positioning_context, earnings_information_surprise, "
        "missing_evidence, risk_notes. Treat information_novelty as whether "
        "the event adds new fundamental information versus recycled narrative. "
        "Treat positioning_effect as whether the event can reset expectations, "
        "confirm existing positioning, contradict positioning, or is neutral. "
        "For earnings calls, distinguish pre-call financial exposure and priced-in "
        "expectations from the new call/report information that forces participants "
        "to adjust commitments.\n\n"
        f"EVENT_JSON={json.dumps(compact, sort_keys=True)}"
    )


def _as_list(value: Any, *, max_items: int = 8) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = [value]
    out = []
    for item in raw:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def _safe_str(value: Any, default: str = "unknown", max_len: int = 500) -> str:
    text = str(value if value is not None else default).strip()
    if not text:
        text = default
    return text[:max_len]


_NEW_INFORMATION_TERMS = {
    "announce",
    "announces",
    "announced",
    "award",
    "awarded",
    "backlog",
    "beat",
    "beats",
    "booking",
    "bookings",
    "contract",
    "customer",
    "deal",
    "forecast",
    "guidance",
    "launch",
    "order",
    "orders",
    "partnership",
    "reports",
    "raises",
    "raised",
    "revenue forecast",
    "selected",
    "supply agreement",
}
_RECYCLED_NARRATIVE_TERMS = {
    "could",
    "may",
    "might",
    "reportedly",
    "rumor",
    "rumour",
    "speculation",
    "why shares",
}
_POSITIONING_RESET_UP_TERMS = {
    "above estimates",
    "ai demand",
    "backlog",
    "beat",
    "beats",
    "bookings",
    "contract",
    "forecast",
    "guidance",
    "hyperscaler",
    "orders",
    "raises",
    "raised",
    "strong demand",
}
_POSITIONING_RESET_DOWN_TERMS = {
    "cut",
    "cuts",
    "delay",
    "delayed",
    "downgrade",
    "miss",
    "misses",
    "probe",
    "shortage",
    "slowing",
    "weak guidance",
}
_CROWDED_LONG_TERMS = {
    "already long",
    "crowded long",
    "priced in",
    "sell the news",
    "high expectations",
    "optimistic positioning",
    "buy the rumor",
}
_CROWDED_SHORT_TERMS = {
    "crowded short",
    "high short interest",
    "heavily shorted",
    "low expectations",
    "not as bad as feared",
    "short squeeze",
}
_EARNINGS_SURPRISE_UP_TERMS = {
    "above expectations",
    "beat expectations",
    "beat estimates",
    "beats expectations",
    "beats estimates",
    "not as bad as feared",
    "raises guidance",
    "raised guidance",
    "strong q&a",
    "unexpected demand",
}
_EARNINGS_SURPRISE_DOWN_TERMS = {
    "below expectations",
    "cut guidance",
    "cuts guidance",
    "missed expectations",
    "missed estimates",
    "misses expectations",
    "misses estimates",
    "weak q&a",
    "unexpected margin pressure",
}


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def infer_information_novelty(event: dict[str, Any]) -> str:
    """Classify whether an event adds fresh information or repeats a narrative."""
    explicit = _safe_str(event.get("information_novelty"), default="", max_len=80)
    if explicit:
        return explicit

    text = " ".join(
        str(event.get(key) or "")
        for key in ("event_summary", "event_type", "event_subtype", "scoring_reason")
    ).lower()
    event_type = str(event.get("event_type") or "").strip().lower()
    confirmation = str(event.get("confirmation_status") or "").strip().lower()

    if event_type == "congressional_trade_disclosure":
        return "delayed_positioning_disclosure"
    if confirmation in {"unconfirmed", "needs_confirmation"} or _contains_any(
        text, _RECYCLED_NARRATIVE_TERMS
    ):
        return "unconfirmed_or_recycled_narrative"
    if event_type in {
        "earnings",
        "guidance",
        "customer_contract",
        "strategic_partnership",
        "supplier_signal",
        "regulatory",
        "lawsuit",
    }:
        return "new_fundamental_information"
    if _contains_any(text, _NEW_INFORMATION_TERMS):
        return "new_fundamental_information"
    return "contextual_information"


def infer_positioning_effect(event: dict[str, Any]) -> str:
    """Classify whether the event can alter current market expectations."""
    explicit = _safe_str(event.get("positioning_effect"), default="", max_len=80)
    if explicit:
        return explicit

    text = " ".join(
        str(event.get(key) or "")
        for key in (
            "event_summary",
            "event_type",
            "event_subtype",
            "intent_direction",
            "expected_market_impact",
            "scoring_reason",
        )
    ).lower()
    novelty = infer_information_novelty(event)
    impact = str(event.get("expected_market_impact") or "").strip().lower()
    direction = str(event.get("intent_direction") or "").strip().lower()

    if novelty in {"unconfirmed_or_recycled_narrative", "contextual_information"}:
        if impact in {"strongly_bullish", "moderately_bullish"}:
            return "positioning_confirmation_constructive"
        if impact in {"strongly_bearish", "moderately_bearish"}:
            return "positioning_confirmation_risk_negative"
        return "neutral_positioning_context"
    if (
        _contains_any(text, _POSITIONING_RESET_UP_TERMS)
        or impact
        in {
            "strongly_bullish",
            "moderately_bullish",
        }
        or direction in {"constructive", "constructive_watch"}
    ):
        return "constructive_expectation_reset"
    if (
        _contains_any(text, _POSITIONING_RESET_DOWN_TERMS)
        or impact
        in {
            "strongly_bearish",
            "moderately_bearish",
        }
        or direction in {"risk_negative", "risk_watch"}
    ):
        return "risk_negative_expectation_reset"
    if novelty == "delayed_positioning_disclosure":
        return "delayed_positioning_context"
    return "neutral_positioning_context"


def infer_earnings_positioning_context(event: dict[str, Any]) -> str:
    """Classify pre-earnings exposure/expectation context when available."""
    explicit = _safe_str(event.get("earnings_positioning_context"), default="", max_len=100)
    if explicit:
        return explicit

    text = " ".join(
        str(event.get(key) or "")
        for key in (
            "event_summary",
            "event_type",
            "event_subtype",
            "scoring_reason",
            "positioning_effect",
        )
    ).lower()
    event_type = str(event.get("event_type") or "").strip().lower()
    if event_type not in {"earnings", "guidance"} and not any(
        term in text for term in ("earnings", "earnings call", "q&a", "guidance")
    ):
        return "not_earnings_specific"
    if _contains_any(text, _CROWDED_LONG_TERMS):
        return "crowded_long_or_good_news_priced_in"
    if _contains_any(text, _CROWDED_SHORT_TERMS):
        return "crowded_short_or_bad_news_priced_in"
    return "positioning_not_observed"


def infer_earnings_information_surprise(event: dict[str, Any]) -> str:
    """Classify whether earnings/call details surprised expectations."""
    explicit = _safe_str(event.get("earnings_information_surprise"), default="", max_len=100)
    if explicit:
        return explicit

    text = " ".join(
        str(event.get(key) or "")
        for key in (
            "event_summary",
            "event_type",
            "event_subtype",
            "expected_market_impact",
            "scoring_reason",
        )
    ).lower()
    event_type = str(event.get("event_type") or "").strip().lower()
    if event_type not in {"earnings", "guidance"} and not any(
        term in text for term in ("earnings", "earnings call", "q&a", "guidance")
    ):
        return "not_earnings_specific"
    if _contains_any(text, _EARNINGS_SURPRISE_UP_TERMS):
        return "positive_information_surprise"
    if _contains_any(text, _EARNINGS_SURPRISE_DOWN_TERMS):
        return "negative_information_surprise"
    if infer_information_novelty(event) == "new_fundamental_information":
        return "new_information_direction_unclear"
    return "no_clear_information_surprise"


def deterministic_event_context(event: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic fallback interpretation."""
    linked_symbols = _as_list(event.get("linked_symbols"))
    symbol = _safe_str(event.get("symbol"), default="")
    affected = linked_symbols or ([symbol] if symbol else [])
    missing = _as_list(event.get("missing_evidence"))
    confirmation = _safe_str(event.get("confirmation_status"), default="unknown")
    source_tier = _safe_str(event.get("source_tier"), default="unknown")
    intent = _safe_str(event.get("intent_category"), default="context_signal")
    direction = _safe_str(event.get("intent_direction"), default="neutral_context")
    summary = _safe_str(event.get("event_summary"), default="No event summary available")
    information_novelty = infer_information_novelty(event)
    positioning_effect = infer_positioning_effect(event)
    earnings_positioning_context = infer_earnings_positioning_context(event)
    earnings_information_surprise = infer_earnings_information_surprise(event)
    if event.get("context_only") is True and linked_symbols:
        summary = (
            f"Context-only {symbol} event may inform linked symbols "
            f"{', '.join(linked_symbols[:5])}: {summary}"
        )

    return {
        "version": AI_EVENT_CONTEXT_VERSION,
        "provider": "deterministic_fallback",
        "runtime_effect": "context_only_no_live_authority",
        "authority": AI_EVENT_CONTEXT_AUTHORITY,
        "summary": summary,
        "intent": intent,
        "affected_symbols": affected,
        "market_alignment": direction,
        "information_novelty": information_novelty,
        "positioning_effect": positioning_effect,
        "earnings_positioning_context": earnings_positioning_context,
        "earnings_information_surprise": earnings_information_surprise,
        "confidence": "low"
        if source_tier in {"unclassified", "low_confidence", "unknown"}
        else "medium",
        "confirmation_status": confirmation,
        "missing_evidence": missing,
        "risk_notes": [
            "interpretation is context-only",
            "does not approve trades or increase size",
        ],
    }


def should_use_semantic_event_provider(event: dict[str, Any]) -> bool:
    """Return true when an event is worth deeper semantic interpretation.

    This deliberately keeps noisy/untrusted routine headlines on the deterministic
    path. LLM interpretation is reserved for reputable or official events that
    are likely to affect risk, catalysts, or cross-symbol context.
    """
    source_tier = str(event.get("source_tier") or "").strip().lower()
    if source_tier not in SEMANTIC_SOURCE_TIERS:
        return False

    event_type = str(event.get("event_type") or "").strip().lower()
    impact = str(event.get("expected_market_impact") or "").strip().lower()
    relevance = str(event.get("trade_relevance") or "").strip().lower()
    direction = str(event.get("intent_direction") or "").strip().lower()
    confirmation = str(event.get("confirmation_status") or "").strip().lower()
    try:
        net_score = abs(float(event.get("net_event_score") or 0.0))
    except Exception:
        net_score = 0.0

    return any(
        (
            event_type in SEMANTIC_EVENT_TYPES,
            impact in SEMANTIC_IMPACTS,
            relevance in SEMANTIC_RELEVANCE,
            direction in {"constructive", "risk_negative", "risk_watch"},
            confirmation in {"official_confirmed", "reputable_reported"},
            net_score >= 6.0,
        )
    )


def _load_provider_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    try:
        loaded = json.loads(str(payload))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def normalize_ai_event_context(
    event: dict[str, Any],
    payload: dict[str, Any] | str,
    *,
    provider_name: str,
) -> dict[str, Any]:
    """Validate provider output and force non-authority fields."""
    fallback = deterministic_event_context(event)
    raw = _load_provider_payload(payload)
    if not raw:
        fallback["provider"] = f"{provider_name}_empty_fallback"
        return fallback

    affected = _as_list(raw.get("affected_symbols") or fallback["affected_symbols"])
    allowed = set(_as_list(event.get("linked_symbols"))) | {str(event.get("symbol") or "").upper()}
    affected = [sym.upper() for sym in affected if sym.upper() in allowed]
    if not affected:
        affected = fallback["affected_symbols"]

    missing = _as_list(raw.get("missing_evidence") or fallback["missing_evidence"])
    risk_notes = _as_list(raw.get("risk_notes") or fallback["risk_notes"])
    risk_notes.append("ai_interpretation_context_only")

    return {
        "version": AI_EVENT_CONTEXT_VERSION,
        "provider": provider_name,
        "runtime_effect": "context_only_no_live_authority",
        "authority": AI_EVENT_CONTEXT_AUTHORITY,
        "summary": _safe_str(raw.get("summary") or fallback["summary"]),
        "intent": _safe_str(raw.get("intent") or fallback["intent"]),
        "affected_symbols": affected,
        "market_alignment": _safe_str(raw.get("market_alignment") or fallback["market_alignment"]),
        "information_novelty": _safe_str(
            raw.get("information_novelty") or fallback["information_novelty"]
        ),
        "positioning_effect": _safe_str(
            raw.get("positioning_effect") or fallback["positioning_effect"]
        ),
        "earnings_positioning_context": _safe_str(
            raw.get("earnings_positioning_context") or fallback["earnings_positioning_context"]
        ),
        "earnings_information_surprise": _safe_str(
            raw.get("earnings_information_surprise") or fallback["earnings_information_surprise"]
        ),
        "confidence": _safe_str(raw.get("confidence") or fallback["confidence"]),
        "confirmation_status": _safe_str(
            raw.get("confirmation_status") or fallback["confirmation_status"]
        ),
        "missing_evidence": missing,
        "risk_notes": risk_notes,
    }


class AIEventContextService:
    def __init__(
        self,
        *,
        config: AIEventContextConfig | None = None,
        provider: Provider | None = None,
    ):
        self.config = config or AIEventContextConfig()
        self.provider = provider

    def interpret(self, event: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled or self.provider is None:
            result = deterministic_event_context(event)
            if (
                self.config.enabled
                and self.provider is None
                and self.config.provider_name != "deterministic"
            ):
                result["provider"] = "enabled_without_provider_fallback"
            return result

        prompt = build_ai_event_context_prompt(event)
        try:
            payload = self.provider(prompt)
            return normalize_ai_event_context(
                event,
                payload,
                provider_name=self.config.provider_name,
            )
        except Exception as exc:
            fallback = deterministic_event_context(event)
            fallback["provider"] = f"{self.config.provider_name}_error_fallback"
            fallback["provider_error"] = str(exc)[:240]
            return fallback


class SelectiveAIEventContextService:
    """Use semantic AI only for high-value events, deterministic otherwise."""

    def __init__(
        self,
        *,
        semantic_service: AIEventContextService,
        fallback_service: AIEventContextService | None = None,
    ):
        self.semantic_service = semantic_service
        self.fallback_service = fallback_service or AIEventContextService(
            config=AIEventContextConfig(enabled=True, provider_name="deterministic"),
            provider=None,
        )

    def interpret(self, event: dict[str, Any]) -> dict[str, Any]:
        if should_use_semantic_event_provider(event):
            result = self.semantic_service.interpret(event)
            result["selection_policy"] = "semantic_high_value_event"
            return result
        result = self.fallback_service.interpret(event)
        result["selection_policy"] = "deterministic_low_value_or_untrusted_event"
        return result


def anthropic_event_context_provider(*, model: str = "claude-3-5-haiku-latest") -> Provider:
    """Return a lazy Anthropic provider for event context interpretation."""
    client: Any | None = None

    def _provider(prompt: str) -> str:
        nonlocal client
        if client is None:
            try:
                from anthropic import Anthropic
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "anthropic is required for AI event context interpretation"
                ) from exc
            client = Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=600,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = []
        for item in getattr(response, "content", []) or []:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)

    return _provider
