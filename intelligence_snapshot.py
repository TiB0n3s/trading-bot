#!/usr/bin/env python3
"""
Compact intelligence snapshot for /status and CLI use.
"""

import json
from pathlib import Path

from bot_events import fetch_events
from intelligence_freshness import get_intelligence_freshness


BASE_DIR = Path(__file__).resolve().parent

FILES = {
    "strategy_memory": BASE_DIR / "strategy_memory.json",
    "policy_backtest": BASE_DIR / "policy_backtest_summary.json",
    "portfolio_replacement": BASE_DIR / "portfolio_replacement_memory.json",
    "missed_opportunity": BASE_DIR / "missed_opportunity_memory.json",
    "excursion": BASE_DIR / "excursion_memory.json",
}


def _load(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _latest_event(event_type):
    try:
        rows = fetch_events(limit=1, event_type=event_type)
        if not rows:
            return None
        r = rows[0]
        return {
            "timestamp": r["timestamp"],
            "event_type": r["event_type"],
            "symbol": r["symbol"],
            "action": r["action"],
            "decision": r["decision"],
            "severity": r["severity"],
            "reason": r["reason"],
            "source": r["source"],
        }
    except Exception as e:
        return {"error": str(e)}


def get_intelligence_snapshot():
    strategy = _load(FILES["strategy_memory"]) or {}
    policy = _load(FILES["policy_backtest"]) or {}
    replacement = _load(FILES["portfolio_replacement"]) or {}
    missed = _load(FILES["missed_opportunity"]) or {}
    excursion = _load(FILES["excursion"]) or {}

    weakest = replacement.get("weakest_holding") or {}
    strongest = replacement.get("strongest_candidate") or {}

    missed_categories = missed.get("category_memory") or {}
    macro_limit = missed_categories.get("macro_position_limit") or {}

    return {
        "strategy_memory": {
            "available": bool(strategy),
            "generated_at": strategy.get("generated_at"),
            "trade_count": strategy.get("trade_count"),
            "manual_overrides_applied": strategy.get("manual_overrides_applied"),
            "history_snapshot": strategy.get("history_snapshot"),
        },
        "policy_backtest": {
            "available": bool(policy),
            "generated_at": policy.get("generated_at"),
            "recommendation": policy.get("recommendation"),
            "reason": policy.get("reason"),
            "rows_analyzed": policy.get("rows_analyzed"),
            "actual_approved": policy.get("actual_approved"),
            "actual_rejected": policy.get("actual_rejected"),
            "hard_gate_rejected": policy.get("hard_gate_rejected"),
            "policy_relevant_rejected": policy.get("policy_relevant_rejected"),
            "policy_would_allow_policy_relevant_rejected": policy.get(
                "policy_would_allow_policy_relevant_rejected"
            ),
        },
        "portfolio_replacement": {
            "available": bool(replacement),
            "generated_at": replacement.get("generated_at"),
            "mode": replacement.get("mode"),
            "recommendation": replacement.get("recommendation"),
            "reason": replacement.get("reason"),
            "open_position_count": replacement.get("open_position_count"),
            "weakest_holding": {
                "symbol": weakest.get("symbol"),
                "unrealized_pl": weakest.get("unrealized_pl"),
                "unrealized_plpc": weakest.get("unrealized_plpc"),
            },
            "strongest_candidate": {
                "symbol": strongest.get("symbol"),
                "score": strongest.get("score"),
                "decision": strongest.get("decision"),
                "buy_opportunity_score": strongest.get("buy_opportunity_score"),
                "buy_opportunity_recommendation": strongest.get("buy_opportunity_recommendation"),
                "session_trend_label": strongest.get("session_trend_label"),
                "setup_label": strongest.get("setup_label"),
                "setup_policy_action": strongest.get("setup_policy_action"),
            },
            "replacement_candidate_count": len(replacement.get("replacement_candidates") or []),
        },
        "missed_opportunity": {
            "available": bool(missed),
            "generated_at": missed.get("generated_at"),
            "signals_analyzed": missed.get("signals_analyzed"),
            "signals_with_bar_data": missed.get("signals_with_bar_data"),
            "macro_position_limit": {
                "recommendation": macro_limit.get("recommendation"),
                "reason": macro_limit.get("reason"),
                "signals": macro_limit.get("signals"),
                "missed_good_rate_pct": macro_limit.get("missed_good_rate_pct"),
                "good_reject_rate_pct": macro_limit.get("good_reject_rate_pct"),
                "avg_30m_return_pct": macro_limit.get("avg_30m_return_pct"),
            },
        },
        "excursion": {
            "available": bool(excursion),
            "generated_at": excursion.get("generated_at"),
            "trades_analyzed": excursion.get("trades_analyzed"),
            "trades_with_bar_data": excursion.get("trades_with_bar_data"),
        },
        "freshness": get_intelligence_freshness(),
        "recent_events": {
            "decision_policy_size_down": _latest_event("DECISION_POLICY_SIZE_DOWN"),
            "portfolio_rotation": _latest_event("PORTFOLIO_ROTATION"),
            "portfolio_rotation_order": _latest_event("PORTFOLIO_ROTATION_ORDER"),
            "position_manager": _latest_event("POSITION_MANAGER"),
            "portfolio_replacement": _latest_event("PORTFOLIO_REPLACEMENT"),
        },
    }


if __name__ == "__main__":
    print(json.dumps(get_intelligence_snapshot(), indent=2, sort_keys=True))
