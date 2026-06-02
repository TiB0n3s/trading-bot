"""Portfolio-specific AI analytics tool profiles.

This module turns the operator's approved ticker universe into structured,
auditable analytics guidance. It does not fetch data, call AI APIs, approve
trades, reject trades, size orders, or submit orders.
"""

from __future__ import annotations

from typing import Any

from symbols_config import CORRELATION_CLUSTERS, SYMBOL_CONFIG


PORTFOLIO_AI_TOOLKIT_VERSION = "portfolio_ai_toolkit_v1"
EARNINGS_ANALYSIS_CONTRACT_VERSION = "earnings_analysis_contract_v1"


ORDER_BOOK_FOCUS = {
    "AAPL",
    "AMD",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "QQQ",
    "SPY",
    "TSLA",
}

MEAN_REVERSION_SYMBOLS = {
    "COST",
    "KO",
    "LIN",
    "MA",
    "MRK",
    "UNH",
    "V",
    "VZ",
    "T",
}

MOMENTUM_CASCADE_SYMBOLS = {
    "AVGO",
    "CRDO",
    "GEV",
    "NVDA",
    "RKLB",
    "TSLA",
    "VRT",
}

STAT_ARB_ANCHORS = {
    "MSFT": ["QQQ", "AAPL", "GOOGL"],
    "NVDA": ["QQQ", "AMD", "AVGO", "ASML"],
    "AMD": ["QQQ", "NVDA", "AVGO", "ASML"],
    "AVGO": ["QQQ", "NVDA", "AMD", "ASML"],
    "META": ["QQQ", "GOOGL", "AAPL"],
    "GOOGL": ["QQQ", "META", "MSFT"],
    "AAPL": ["QQQ", "MSFT", "META"],
    "SPY": ["QQQ", "IWM"],
    "QQQ": ["SPY", "MSFT", "NVDA", "AAPL"],
}

CONTAGION_MAP = {
    "ASML": ["NVDA", "AMD", "AVGO", "TSM", "SNPS"],
    "AVGO": ["NVDA", "AMD", "CRDO", "VRT"],
    "NVDA": ["AMD", "AVGO", "QQQ", "VRT", "DELL", "SMCI"],
    "AMD": ["NVDA", "AVGO", "QQQ"],
    "CRM": ["ORCL", "MSFT", "VRT", "ADSK", "MDB"],
    "ORCL": ["CRM", "MSFT", "VRT", "DELL"],
    "MSFT": ["GOOGL", "META", "ORCL", "VRT", "NVDA"],
    "META": ["GOOGL", "MSFT", "NVDA"],
    "GOOGL": ["META", "MSFT", "NVDA"],
    "LLY": ["MRK", "ABBV", "VRTX", "UNH"],
    "VRTX": ["LLY", "MRK", "ABBV", "MRNA"],
    "CAT": ["GE", "GEV", "LIN", "TSCO"],
    "CVX": ["XOM"],
    "XOM": ["CVX"],
    "LMT": ["RTX", "RKLB", "HWM"],
    "RTX": ["LMT", "RKLB", "HWM"],
}

SECTOR_EVENT_FOCUS = {
    "energy": {
        "alternative_data": ["refinery_activity", "shipping_logistics"],
        "status": "not_integrated",
    },
    "defense": {
        "alternative_data": ["supply_chain_logistics", "contract_awards"],
        "status": "event_context_only",
    },
    "healthcare": {
        "earnings_focus": ["pipeline_language", "trial_language", "regulatory_risk"],
        "status": "event_context_only",
    },
    "mega_cap_tech": {
        "earnings_focus": ["capex_vs_fcf", "ai_demand", "management_tone"],
        "status": "event_context_only",
    },
    "software_infra": {
        "earnings_focus": ["rpo_backlog", "enterprise_spending", "cloud_timing"],
        "status": "event_context_only",
    },
    "consumer": {
        "earnings_focus": ["inventory_anomalies", "margin_pressure", "demand_elasticity"],
        "status": "event_context_only",
    },
}

EARNINGS_SYSTEM_PROMPT = (
    "You are an elite quantitative equity analyst specializing in large-cap "
    "stocks. Analyze earnings text strictly for financial anomalies, structural "
    "risks, and micro-linguistic shifts. Do not summarize generic optimistic "
    "statements. Output exactly four sections: Guidance Nuances, Linguistic "
    "Hedging, Contagion Risk, Accounting/Inventory Flags."
)


def _symbol(symbol: str | None) -> str:
    return str(symbol or "").upper().strip()


def _clusters(symbol: str) -> list[str]:
    return list((SYMBOL_CONFIG.get(symbol) or {}).get("clusters") or [])


def _cluster_peers(symbol: str, limit: int = 8) -> list[str]:
    peers: list[str] = []
    for cluster in _clusters(symbol):
        for peer in sorted(CORRELATION_CLUSTERS.get(cluster, [])):
            if peer != symbol and peer not in peers:
                peers.append(peer)
    return peers[:limit]


def _tool_status(symbol: str, tool: str) -> str:
    if tool == "order_book_dynamics":
        return "proxy_only" if symbol in ORDER_BOOK_FOCUS else "not_primary"
    if tool == "alternative_data_matching":
        clusters = set(_clusters(symbol))
        if clusters & {"energy"}:
            return "not_integrated"
        if clusters & {"defense", "industrials", "consumer", "healthcare"}:
            return "event_context_only"
        return "not_primary"
    if tool == "nlp_sentiment_filters":
        return "event_context_only"
    if tool == "correlation_cluster_analysis":
        return "active"
    if tool == "macro_environment_mapping":
        return "active"
    return "unknown"


def symbol_strategy_archetypes(symbol: str | None) -> list[dict[str, Any]]:
    """Return practical strategy archetypes relevant to one symbol."""
    sym = _symbol(symbol)
    archetypes = []
    if sym in STAT_ARB_ANCHORS:
        archetypes.append({
            "name": "statistical_arbitrage",
            "status": "candidate_research_only",
            "pairs": STAT_ARB_ANCHORS[sym],
        })
    if sym in MEAN_REVERSION_SYMBOLS:
        archetypes.append({
            "name": "mean_reversion",
            "status": "candidate_research_only",
            "trigger_family": "volatility_band_extension",
        })
    if sym in MOMENTUM_CASCADE_SYMBOLS:
        archetypes.append({
            "name": "momentum_cascade",
            "status": "candidate_research_only",
            "trigger_family": "trend_continuation_plus_peer_confirmation",
        })
    if not archetypes:
        archetypes.append({
            "name": "general_momentum_or_pullback",
            "status": "context_dependent",
        })
    return archetypes


def earnings_analysis_contract(symbol: str | None = None) -> dict[str, Any]:
    """Return the structured earnings/transcript analysis contract."""
    sym = _symbol(symbol)
    return {
        "version": EARNINGS_ANALYSIS_CONTRACT_VERSION,
        "symbol": sym or None,
        "runtime_effect": "research_alert_only_no_trade_authority",
        "system_prompt": EARNINGS_SYSTEM_PROMPT,
        "required_sections": [
            "guidance_nuances",
            "linguistic_hedging",
            "contagion_risk",
            "accounting_inventory_flags",
        ],
        "score_fields": {
            "ai_sentiment_score": "integer -10..10",
            "guidance_risk_score": "integer 0..100",
            "contagion_risk_score": "integer 0..100",
            "accounting_risk_score": "integer 0..100",
            "confidence": "low|medium|high",
        },
        "peer_watchlist": symbol_contagion_watchlist(sym),
    }


def symbol_contagion_watchlist(symbol: str | None, limit: int = 10) -> list[str]:
    sym = _symbol(symbol)
    direct = [peer for peer in CONTAGION_MAP.get(sym, []) if peer in SYMBOL_CONFIG]
    peers = _cluster_peers(sym, limit=limit)
    out = []
    for peer in direct + peers:
        if peer != sym and peer not in out:
            out.append(peer)
    return out[:limit]


def symbol_ai_tool_profile(symbol: str | None) -> dict[str, Any]:
    """Build a compact per-symbol AI analytics profile."""
    sym = _symbol(symbol)
    clusters = _clusters(sym)
    sector_focus = []
    for cluster in clusters:
        if cluster in SECTOR_EVENT_FOCUS:
            sector_focus.append({"cluster": cluster, **SECTOR_EVENT_FOCUS[cluster]})

    return {
        "version": PORTFOLIO_AI_TOOLKIT_VERSION,
        "symbol": sym or None,
        "clusters": clusters,
        "analytics_tools": {
            "order_book_dynamics": {
                "status": _tool_status(sym, "order_book_dynamics"),
                "current_proxy": "execution_quality_and_market_microstructure",
            },
            "correlation_cluster_analysis": {
                "status": _tool_status(sym, "correlation_cluster_analysis"),
                "cluster_peers": _cluster_peers(sym),
            },
            "alternative_data_matching": {
                "status": _tool_status(sym, "alternative_data_matching"),
                "guardrail": "do_not_infer_without_configured_feed",
            },
            "nlp_sentiment_filters": {
                "status": _tool_status(sym, "nlp_sentiment_filters"),
                "current_source": "daily_symbol_events_and_market_brief",
            },
            "macro_environment_mapping": {
                "status": _tool_status(sym, "macro_environment_mapping"),
                "benchmarks": ["SPY", "QQQ", "IWM", "GLD"],
            },
        },
        "strategy_archetypes": symbol_strategy_archetypes(sym),
        "contagion_watchlist": symbol_contagion_watchlist(sym),
        "sector_event_focus": sector_focus[:3],
        "earnings_contract_version": EARNINGS_ANALYSIS_CONTRACT_VERSION,
        "external_workflow": {
            "trigger": "sec_or_transcript_alert",
            "data_aggregators": ["finnhub", "polygon"],
            "ai_analysis": ["openai_api", "anthropic_api"],
            "dashboard_targets": ["slack", "notion", "google_sheets"],
            "status": "not_configured",
        },
        "guardrails": {
            "no_new_trade_authority": True,
            "external_feeds_must_be_configured": True,
        },
    }
