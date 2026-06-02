"""Context-only AI interpretation for collected market events.

This service is intentionally non-authoritative. It can summarize source
evidence and clarify intent, but it cannot approve, reject, size, or alter
execution. Live collection must explicitly opt in before any LLM call is made.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable


AI_EVENT_CONTEXT_VERSION = "ai_event_context_v1"
AI_EVENT_CONTEXT_AUTHORITY = "context_only_no_standalone_buy_authority"

Provider = Callable[[str], dict[str, Any] | str]


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
    }
    return (
        "Interpret this market event for context only. Do not make a trading "
        "recommendation. Do not infer bullish authority from delayed, rumor, "
        "unconfirmed, or context-only evidence. Return JSON only with keys: "
        "summary, intent, affected_symbols, market_alignment, confidence, "
        "confirmation_status, missing_evidence, risk_notes.\n\n"
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
        "confidence": "low" if source_tier in {"unclassified", "low_confidence", "unknown"} else "medium",
        "confirmation_status": confirmation,
        "missing_evidence": missing,
        "risk_notes": [
            "interpretation is context-only",
            "does not approve trades or increase size",
        ],
    }


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
        "market_alignment": _safe_str(
            raw.get("market_alignment") or fallback["market_alignment"]
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
