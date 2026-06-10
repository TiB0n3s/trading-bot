"""Financial text sentiment scoring with optional transformer readiness."""

from __future__ import annotations

import re
from typing import Any

from services.optional_dependency_service import optional_dependency_status

FINANCIAL_SENTIMENT_VERSION = "financial_sentiment_v1"

POSITIVE_TERMS = {
    "beat",
    "raise",
    "raised",
    "growth",
    "accelerating",
    "strong",
    "record",
    "demand",
    "margin expansion",
    "pricing power",
    "backlog growth",
    "free cash flow growth",
}

NEGATIVE_TERMS = {
    "miss",
    "cut",
    "delay",
    "delayed",
    "slowing",
    "weak",
    "margin pressure",
    "inventory write-down",
    "cash burn",
    "regulatory risk",
    "supply constraint",
    "lowered guidance",
}

HEDGING_TERMS = {
    "might",
    "could",
    "subject to",
    "feasible",
    "approximately",
    "around",
    "uncertain",
    "depending on",
    "visibility",
}


def _count_terms(text: str, terms: set[str]) -> int:
    total = 0
    lower = text.lower()
    for term in terms:
        total += len(re.findall(rf"\b{re.escape(term)}\b", lower))
    return total


def score_financial_text(text: str | None) -> dict[str, Any]:
    text = text or ""
    positive = _count_terms(text, POSITIVE_TERMS)
    negative = _count_terms(text, NEGATIVE_TERMS)
    hedging = _count_terms(text, HEDGING_TERMS)
    raw = positive - negative - hedging * 0.5
    score = max(-10.0, min(10.0, raw * 2.0))
    if score >= 3:
        label = "positive"
    elif score <= -3:
        label = "negative"
    else:
        label = "neutral"
    deps = optional_dependency_status()["packages"]
    finbert_available = bool(deps.get("transformers", {}).get("available"))
    return {
        "version": FINANCIAL_SENTIMENT_VERSION,
        "label": label,
        "score": round(score, 4),
        "positive_term_count": positive,
        "negative_term_count": negative,
        "hedging_term_count": hedging,
        "model_provider": "lexicon_fallback",
        "finbert_available": finbert_available,
        "runtime_effect": "research_signal_only_no_trade_authority",
        "upgrade_path": "install transformers and configured FinBERT model for local inference",
    }


_finbert_pipeline = None


def score_financial_text_finbert(
    text: str | None,
    *,
    model_name: str = "ProsusAI/finbert",
    max_chars: int = 2000,
) -> dict[str, Any]:
    """Score text with FinBERT when available, falling back to lexicon scoring."""
    global _finbert_pipeline
    text = text or ""
    deps = optional_dependency_status()["packages"]
    if not deps.get("transformers", {}).get("available"):
        result = score_financial_text(text)
        result["model_provider"] = "lexicon_fallback_transformers_unavailable"
        return result
    try:
        if _finbert_pipeline is None:
            from transformers import pipeline

            _finbert_pipeline = pipeline("sentiment-analysis", model=model_name)
        raw = _finbert_pipeline(text[:max_chars])
        item = raw[0] if raw else {}
        label_raw = str(item.get("label") or "neutral").lower()
        confidence = float(item.get("score") or 0.0)
        if "positive" in label_raw:
            score = confidence * 10.0
            label = "positive"
        elif "negative" in label_raw:
            score = -confidence * 10.0
            label = "negative"
        else:
            score = 0.0
            label = "neutral"
        return {
            "version": FINANCIAL_SENTIMENT_VERSION,
            "label": label,
            "score": round(score, 4),
            "positive_term_count": None,
            "negative_term_count": None,
            "hedging_term_count": _count_terms(text, HEDGING_TERMS),
            "model_provider": f"transformers:{model_name}",
            "finbert_available": True,
            "model_confidence": round(confidence, 4),
            "runtime_effect": "research_signal_only_no_trade_authority",
            "upgrade_path": "loaded local transformers pipeline",
        }
    except Exception as exc:
        result = score_financial_text(text)
        result["model_provider"] = "lexicon_fallback_finbert_error"
        result["finbert_error"] = str(exc)
        return result
