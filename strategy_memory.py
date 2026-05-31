#!/usr/bin/env python3
"""
Lazy strategy-memory loader for live trading decisions.

Reads strategy_memory.json produced by strategy_learner.py.
"""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from policy_artifacts import policy_artifacts_enabled

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "strategy_memory.json"

_strategy_memory = {}
_strategy_memory_mtime = 0.0


class StrategyMemoryRecommendation(str, Enum):
    AVOID = "avoid"
    CAUTION = "caution"
    NEUTRAL = "neutral"
    OBSERVE = "observe"
    FAVOR = "favor"
    NONE = "none"


@dataclass(frozen=True)
class StrategyMemoryContext:
    setup_label: str = "unknown"
    prediction_decision: str = "unknown"
    buy_opportunity_recommendation: str = "unknown"
    session_trend_label: str = "unknown"

    def to_lookup_context(self) -> dict[str, dict[str, str]]:
        return {
            "setup": {"setup_label": self.setup_label},
            "prediction": {"prediction_decision": self.prediction_decision},
            "buy_opportunity": {
                "buy_opportunity_recommendation": self.buy_opportunity_recommendation
            },
            "session_momentum": {"trend_label": self.session_trend_label},
        }


def _clean_context_value(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value).strip()
    return text if text else "unknown"


def _load_strategy_memory():
    global _strategy_memory, _strategy_memory_mtime

    if not policy_artifacts_enabled():
        return {}

    if not MEMORY_FILE.exists():
        return {}

    try:
        mtime = MEMORY_FILE.stat().st_mtime
        if mtime <= _strategy_memory_mtime:
            return _strategy_memory

        _strategy_memory = json.loads(MEMORY_FILE.read_text())
        _strategy_memory_mtime = mtime

        logger.info(
            "Strategy memory loaded: "
            f"trade_count={_strategy_memory.get('trade_count')} "
            f"generated_at={_strategy_memory.get('generated_at')}"
        )

    except Exception as e:
        logger.error(f"Failed to load strategy memory: {e}")
        _strategy_memory = {}

    return _strategy_memory


def _worst_recommendation(recommendations):
    order = {
        StrategyMemoryRecommendation.AVOID.value: 4,
        StrategyMemoryRecommendation.CAUTION.value: 3,
        StrategyMemoryRecommendation.NEUTRAL.value: 2,
        StrategyMemoryRecommendation.OBSERVE.value: 1,
        StrategyMemoryRecommendation.FAVOR.value: 0,
        StrategyMemoryRecommendation.NONE.value: 0,
        None: 0,
    }
    return max(recommendations, key=lambda item: order.get(item, 0)) if recommendations else None


def normalize_strategy_memory_context(signal_context) -> StrategyMemoryContext:
    ctx = signal_context or {}
    if not isinstance(ctx, dict):
        return StrategyMemoryContext()
    setup_obs = ctx.get("setup_observation") or {}
    setup_quality = ctx.get("setup_quality") or setup_obs.get("setup_quality") or {}
    buy_opportunity = ctx.get("buy_opportunity") or {}
    prediction = ctx.get("prediction") or ctx.get("prediction_gate") or {}
    session = ctx.get("session_momentum") or {}

    return StrategyMemoryContext(
        setup_label=_clean_context_value(
            (
                setup_obs.get("setup_label")
                or setup_quality.get("label")
                or ctx.get("setup_label")
            )
        ),
        prediction_decision=_clean_context_value(
            (
                prediction.get("prediction_decision")
                or ctx.get("prediction_decision")
            )
        ),
        buy_opportunity_recommendation=_clean_context_value(
            (
                buy_opportunity.get("buy_opportunity_recommendation")
                or buy_opportunity.get("recommendation")
                or ctx.get("buy_opportunity_recommendation")
            )
        ),
        session_trend_label=_clean_context_value(
            (
                session.get("trend_label")
                or ctx.get("session_trend_label")
            )
        ),
    )


def _summary_from_context_matches(matches):
    match_recs = [m.get("recommendation") for m in matches]
    worst_context_rec = _worst_recommendation(match_recs)
    learned_min_scores = [
        int(m["min_setup_score"])
        for m in matches
        if isinstance(m.get("min_setup_score"), int)
    ]
    return worst_context_rec, learned_min_scores


def memory_for_signal(symbol, signal_context=None):
    """
    Return live memory adjustment for a symbol and current signal context.

    Output is intentionally simple:
    {
      "available": bool,
      "recommendation": "favor|neutral|caution|avoid|observe",
      "min_setup_score": int,
      "reason": str,
      "symbol_memory": {...}
    }
    """
    mem = _load_strategy_memory()
    if not mem:
        return {
            "available": False,
            "recommendation": "none",
            "min_setup_score": None,
            "reason": (
                "policy artifacts disabled"
                if not policy_artifacts_enabled()
                else "strategy_memory.json unavailable"
            ),
        }

    symbol = (symbol or "").upper()
    symbols = mem.get("symbols") or {}
    symbol_mem = symbols.get(symbol)
    context_memory = contextual_memory_for_signal(
        symbol,
        normalize_strategy_memory_context(signal_context).to_lookup_context(),
        memory_override=mem,
    )
    matches = context_memory.get("matches") or []

    if not symbol_mem:
        context_rec, learned_min_scores = _summary_from_context_matches(matches)
        return {
            "available": True,
            "recommendation": context_rec or "observe",
            "min_setup_score": max(learned_min_scores) if learned_min_scores else None,
            "reason": f"no symbol memory for {symbol}",
            "context_matches": matches,
        }

    rec = symbol_mem.get("recommendation", "observe")
    min_score = symbol_mem.get("min_setup_score")
    worst_context_rec, learned_min_scores = _summary_from_context_matches(matches)
    if learned_min_scores:
        score_candidates = learned_min_scores[:]
        if isinstance(min_score, int):
            score_candidates.append(min_score)
        min_score = max(score_candidates)
    if worst_context_rec in ("avoid", "caution"):
        rec = worst_context_rec
    elif worst_context_rec == "favor" and rec in ("observe", "neutral"):
        rec = "favor"

    return {
        "available": True,
        "recommendation": rec,
        "min_setup_score": min_score,
        "reason": symbol_mem.get("reason"),
        "symbol_memory": symbol_mem,
        "context_matches": matches,
        "generated_at": mem.get("generated_at"),
        "lookback_days": mem.get("lookback_days"),
    }

def get_strategy_memory():
    """Public accessor for the full strategy memory document."""
    return _load_strategy_memory()


def contextual_memory_for_signal(symbol, intelligence_context=None, memory_override=None):
    """
    Return symbol + contextual learned memory for the current signal.

    Uses sections generated by strategy_learner.py:
    - symbols
    - setup_label_context
    - prediction_decision_context
    - buy_opportunity_context
    - session_trend_context
    - symbol_setup_label_context
    - symbol_prediction_context
    - symbol_buy_opportunity_context
    - symbol_session_trend_context

    memory_override: if provided, use this dict instead of loading from
    strategy_memory.json. Used by replay tools to inject point-in-time
    archived strategy memory rather than the current live file.
    """
    mem = memory_override if memory_override is not None else _load_strategy_memory()
    if not mem:
        return {
            "available": False,
            "reason": (
                "policy artifacts disabled"
                if not policy_artifacts_enabled()
                else "strategy_memory.json unavailable"
            ),
            "matches": [],
        }

    symbol = (symbol or "").upper()
    ctx = intelligence_context or {}

    setup = ctx.get("setup") or {}
    prediction = ctx.get("prediction") or {}
    buy_opp = ctx.get("buy_opportunity") or {}
    session = ctx.get("session_momentum") or {}

    setup_label = setup.get("setup_label") or "unknown"
    prediction_decision = prediction.get("prediction_decision") or "unknown"
    buy_opp_rec = buy_opp.get("buy_opportunity_recommendation") or "unknown"
    session_label = session.get("trend_label") or "unknown"

    lookups = [
        ("symbol", "symbols", symbol),
        ("setup_label", "setup_label_context", setup_label),
        ("prediction_decision", "prediction_decision_context", prediction_decision),
        ("buy_opportunity", "buy_opportunity_context", buy_opp_rec),
        ("session_trend", "session_trend_context", session_label),
        ("symbol_setup_label", "symbol_setup_label_context", f"{symbol}|{setup_label}"),
        ("symbol_prediction", "symbol_prediction_context", f"{symbol}|{prediction_decision}"),
        ("symbol_buy_opportunity", "symbol_buy_opportunity_context", f"{symbol}|{buy_opp_rec}"),
        ("symbol_session_trend", "symbol_session_trend_context", f"{symbol}|{session_label}"),
    ]

    matches = []
    for label, section, key in lookups:
        data = (mem.get(section) or {}).get(key)
        if data:
            matches.append({
                "label": label,
                "section": section,
                "key": key,
                "recommendation": data.get("recommendation"),
                "min_setup_score": data.get("min_setup_score"),
                "expectancy": data.get("expectancy"),
                "win_rate_pct": data.get("win_rate_pct"),
                "trades": data.get("trades"),
                "reason": data.get("reason"),
                "manual_override": data.get("manual_override", False),
            })

    return {
        "available": True,
        "generated_at": mem.get("generated_at"),
        "lookback_days": mem.get("lookback_days"),
        "matches": matches,
    }
