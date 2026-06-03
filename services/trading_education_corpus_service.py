"""Curated trading education source contract.

This is intentionally a source-policy layer, not a scraper.  It defines what
the AI/ML education corpus may ingest or reference before any crawler is added.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse


TRADING_EDUCATION_CORPUS_VERSION = "trading_education_corpus_v1"
TRADING_EDUCATION_RUNTIME_EFFECT = "education_context_only_no_trade_authority"


@dataclass(frozen=True)
class TradingEducationSource:
    key: str
    name: str
    source_type: str
    tier: str
    url: str | None
    topics: tuple[str, ...]
    ingestion_status: str
    link_follow_policy: str
    authority: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["topics"] = list(self.topics)
        return data


@dataclass(frozen=True)
class TradingEducationConcept:
    key: str
    name: str
    concept_type: str
    summary: str
    bot_usage: str
    live_authority: str
    related_features: tuple[str, ...]
    guardrails: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["related_features"] = list(self.related_features)
        data["guardrails"] = list(self.guardrails)
        return data


CURATED_TRADING_EDUCATION_SOURCES: tuple[TradingEducationSource, ...] = (
    TradingEducationSource(
        key="sec_investor_education",
        name="SEC Investor.gov / Investor Education",
        source_type="official_regulator",
        tier="official_highest",
        url="https://www.investor.gov/",
        topics=("investing_basics", "risk", "fraud_avoidance", "disclosures"),
        ingestion_status="approved_seed",
        link_follow_policy="same_domain_only",
        authority="education_context_only",
        notes="Plain-English investor education. Use for baseline concepts, not trade signals.",
    ),
    TradingEducationSource(
        key="finra_investing_basics",
        name="FINRA Investing Basics",
        source_type="official_regulator",
        tier="official_highest",
        url="https://www.finra.org/investors/investing/investing-basics",
        topics=("investing_basics", "products", "brokerage_accounts", "margin"),
        ingestion_status="approved_seed",
        link_follow_policy="same_domain_only",
        authority="education_context_only",
        notes="Useful for account, product, margin, and risk mechanics.",
    ),
    TradingEducationSource(
        key="cftc_futures_basics",
        name="CFTC Futures Market Basics",
        source_type="official_regulator",
        tier="official_highest",
        url="https://www.cftc.gov/LearnAndProtect/EducationCenter/FuturesMarketBasics/index2.htm",
        topics=("futures", "derivatives", "risk"),
        ingestion_status="approved_seed",
        link_follow_policy="same_domain_only",
        authority="education_context_only",
        notes="Use for futures mechanics and risk framing if futures enter scope.",
    ),
    TradingEducationSource(
        key="cme_education",
        name="CME Group Education",
        source_type="exchange_education",
        tier="official_high",
        url="https://www.cmegroup.com/education.html",
        topics=("futures", "market_structure", "derivatives", "risk_management"),
        ingestion_status="approved_seed",
        link_follow_policy="same_domain_only",
        authority="education_context_only",
        notes="Exchange education. Useful for market mechanics, not directional signal authority.",
    ),
    TradingEducationSource(
        key="nerdwallet_investing",
        name="NerdWallet Investing Education",
        source_type="consumer_education",
        tier="medium_education",
        url="https://www.nerdwallet.com/investing",
        topics=("investing_basics", "personal_finance", "beginner_guides"),
        ingestion_status="approved_context_seed",
        link_follow_policy="same_domain_only",
        authority="education_context_only",
        notes="Good beginner explanations. Not a market-moving source or live authority source.",
    ),
    TradingEducationSource(
        key="investopedia",
        name="Investopedia",
        source_type="financial_glossary_education",
        tier="medium_education",
        url="https://www.investopedia.com/",
        topics=("glossary", "technical_terms", "beginner_guides", "simulator_context"),
        ingestion_status="approved_context_seed",
        link_follow_policy="same_domain_only",
        authority="education_context_only",
        notes="Useful for definitions and broad concepts. Validate critical claims against official sources.",
    ),
    TradingEducationSource(
        key="intelligent_investor",
        name="The Intelligent Investor by Benjamin Graham",
        source_type="book",
        tier="classic_reference",
        url=None,
        topics=("value_investing", "margin_of_safety", "investor_psychology"),
        ingestion_status="metadata_only",
        link_follow_policy="no_web_following",
        authority="education_context_only",
        notes="Reference concepts only. Do not ingest copyrighted full text.",
    ),
    TradingEducationSource(
        key="unshakable",
        name="Unshakable by Tony Robbins",
        source_type="book",
        tier="general_reference",
        url=None,
        topics=("long_term_investing", "personal_finance", "risk_awareness"),
        ingestion_status="metadata_only",
        link_follow_policy="no_web_following",
        authority="education_context_only",
        notes="Reference concepts only. Do not ingest copyrighted full text.",
    ),
    TradingEducationSource(
        key="ric_edelman",
        name="Ric Edelman books and podcast",
        source_type="book_podcast",
        tier="general_reference",
        url="https://www.ricedelman.com/",
        topics=("financial_planning", "long_term_investing", "personal_finance"),
        ingestion_status="metadata_only",
        link_follow_policy="no_web_following",
        authority="education_context_only",
        notes="Reference at a high level only unless specific public pages are explicitly approved later.",
    ),
    TradingEducationSource(
        key="mobile_investment_apps",
        name="Mobile investment apps and broker education",
        source_type="app_broker_education",
        tier="operator_reference",
        url=None,
        topics=("practice_tools", "beginner_experience", "broker_education"),
        ingestion_status="manual_review_only",
        link_follow_policy="no_web_following",
        authority="education_context_only",
        notes="Use only for awareness of practice/simulator tools. Do not scrape app content.",
    ),
    TradingEducationSource(
        key="trendsetters_consumer_observation",
        name="Trendsetter / consumer observation heuristic",
        source_type="operator_heuristic",
        tier="hypothesis_only",
        url=None,
        topics=("consumer_trends", "peripheral_context", "hypothesis_generation"),
        ingestion_status="manual_review_only",
        link_follow_policy="no_web_following",
        authority="hypothesis_only_no_signal_authority",
        notes="May inspire peripheral-company context hypotheses, never a direct trade signal.",
    ),
    TradingEducationSource(
        key="financial_advisor",
        name="Financial advisor guidance",
        source_type="human_advisor",
        tier="human_guidance",
        url=None,
        topics=("financial_plan", "risk_tolerance", "insurance", "estate_planning"),
        ingestion_status="not_ingested",
        link_follow_policy="no_web_following",
        authority="outside_bot_scope",
        notes="Relevant to personal planning, not automated trading intelligence.",
    ),
)


CURATED_TRADING_EDUCATION_CONCEPTS: tuple[TradingEducationConcept, ...] = (
    TradingEducationConcept(
        key="strategy_vs_style",
        name="Trading strategy versus trading style",
        concept_type="foundation",
        summary=(
            "A trading style describes broad preferences such as time horizon and frequency. "
            "A strategy defines concrete entry, exit, and risk conditions."
        ),
        bot_usage="Use this distinction when labeling policies, reports, and learning buckets.",
        live_authority="education_context_only",
        related_features=("strategy_label", "holding_time", "entry_rule", "exit_rule"),
        guardrails=("Do not confuse style labels with executable strategy rules.",),
    ),
    TradingEducationConcept(
        key="trend_trading",
        name="Trend trading",
        concept_type="strategy_taxonomy",
        summary=(
            "A trend strategy seeks continuation while price and momentum point in the same "
            "direction, usually tolerating temporary retracements until reversal evidence appears."
        ),
        bot_usage="Map to trend-continuation setup review, regime routing, and exit deterioration checks.",
        live_authority="education_context_only",
        related_features=("trend_slope", "relative_strength", "adx_like_strength", "pullback_depth"),
        guardrails=("Require regime, breadth, and execution-quality confirmation before promotion.",),
    ),
    TradingEducationConcept(
        key="range_trading",
        name="Range trading",
        concept_type="strategy_taxonomy",
        summary=(
            "A range strategy looks for repeated movement between support and resistance while "
            "breakout evidence remains weak."
        ),
        bot_usage="Use as a classification pattern for mean-reversion or chop regimes.",
        live_authority="education_context_only",
        related_features=("range_width", "support_resistance_distance", "rsi_state", "bollinger_position"),
        guardrails=("Do not apply range assumptions during volatility expansion or confirmed breakout regimes.",),
    ),
    TradingEducationConcept(
        key="breakout_trading",
        name="Breakout trading",
        concept_type="strategy_taxonomy",
        summary=(
            "A breakout strategy enters when price leaves a defined range or level, ideally with "
            "volume, liquidity, and market participation confirming the move."
        ),
        bot_usage="Use for setup-structure scoring, opening-range continuation, and missed-buy review.",
        live_authority="education_context_only",
        related_features=("breakout_level", "volume_expansion", "opening_range_state", "failed_breakout_count"),
        guardrails=("Treat low-volume or liquidity-vacuum breakouts as degraded until outcome evidence supports them.",),
    ),
    TradingEducationConcept(
        key="reversal_trading",
        name="Reversal trading",
        concept_type="strategy_taxonomy",
        summary=(
            "A reversal strategy seeks a confirmed turn from an existing trend rather than a normal "
            "retracement inside that trend."
        ),
        bot_usage="Use for exit-learning, pullback-vs-reversal labeling, and failed-trend diagnostics.",
        live_authority="education_context_only",
        related_features=("reversal_signal", "retracement_depth", "trend_break", "volume_confirmation"),
        guardrails=("Require stronger evidence than a single counter-trend bar.",),
    ),
    TradingEducationConcept(
        key="gap_trading",
        name="Gap trading",
        concept_type="strategy_taxonomy",
        summary=(
            "A gap strategy evaluates the distance between prior close and current open, then "
            "distinguishes gap acceptance, rejection, continuation, and fade behavior."
        ),
        bot_usage="Use for premarket context, opening range, event-driven regime, and downside-asymmetry features.",
        live_authority="education_context_only",
        related_features=("gap_pct", "gap_acceptance", "opening_range_break", "event_context"),
        guardrails=("Do not assume every up-gap is bullish; classify acceptance versus rejection first.",),
    ),
    TradingEducationConcept(
        key="pairs_trading",
        name="Pairs trading",
        concept_type="strategy_taxonomy",
        summary=(
            "Pairs trading compares related instruments and looks for temporary valuation or "
            "relative-strength dislocations."
        ),
        bot_usage="Use for portfolio overlap, peer confirmation, and relative-strength diagnostics.",
        live_authority="education_context_only",
        related_features=("peer_relative_strength", "correlation_cluster", "spread_zscore"),
        guardrails=("Do not introduce short/hedged execution authority without a separate risk model.",),
    ),
    TradingEducationConcept(
        key="arbitrage",
        name="Arbitrage",
        concept_type="strategy_taxonomy",
        summary=(
            "Arbitrage seeks equivalent or near-equivalent assets priced differently, but practical "
            "opportunities are often fleeting and execution-sensitive."
        ),
        bot_usage="Use only as educational market-structure context unless explicit arbitrage infrastructure exists.",
        live_authority="education_context_only",
        related_features=("price_dislocation", "execution_latency", "spread_cost"),
        guardrails=("Do not label ordinary momentum or relative-strength trades as arbitrage.",),
    ),
    TradingEducationConcept(
        key="momentum_trading",
        name="Momentum trading",
        concept_type="strategy_taxonomy",
        summary=(
            "A momentum strategy follows strong directional price movement while monitoring whether "
            "force, volume, and trend participation are still improving."
        ),
        bot_usage="Use for EFI/PVT/bar-pattern learning, buy-opportunity ranking, and sell-discipline review.",
        live_authority="education_context_only",
        related_features=("efi", "pvt", "volume_trend", "momentum_acceleration", "relative_volume"),
        guardrails=("Separate continuation momentum from exhausted chase conditions.",),
    ),
    TradingEducationConcept(
        key="risk_practice_before_live",
        name="Practice and risk validation before live use",
        concept_type="risk_management",
        summary=(
            "Strategies should be tested in replay, paper, or demo mode before real capital exposure, "
            "with explicit risk limits and measured outcomes."
        ),
        bot_usage="Use as governance language for promotion readiness and authority leak tests.",
        live_authority="education_context_only",
        related_features=("paper_mode", "promotion_readiness", "sample_size", "calibration_error"),
        guardrails=("Education concepts do not bypass rollout thresholds or operator review.",),
    ),
)


def approved_domains() -> set[str]:
    domains: set[str] = set()
    for source in CURATED_TRADING_EDUCATION_SOURCES:
        if not source.url or source.ingestion_status in {"metadata_only", "manual_review_only", "not_ingested"}:
            continue
        host = urlparse(source.url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            domains.add(host)
    return domains


def classify_education_url(url: str) -> dict[str, Any]:
    host = urlparse(url or "").netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    for source in CURATED_TRADING_EDUCATION_SOURCES:
        if not source.url:
            continue
        source_host = urlparse(source.url).netloc.lower()
        source_host = source_host[4:] if source_host.startswith("www.") else source_host
        if host == source_host or host.endswith(f".{source_host}"):
            data = source.to_dict()
            data["matched"] = True
            data["source_policy_version"] = TRADING_EDUCATION_CORPUS_VERSION
            return data
    return {
        "matched": False,
        "source_policy_version": TRADING_EDUCATION_CORPUS_VERSION,
        "url": url,
        "tier": "unapproved",
        "ingestion_status": "blocked",
        "link_follow_policy": "no_web_following",
        "authority": "none",
    }


def build_trading_education_health_payload() -> dict[str, Any]:
    sources = [source.to_dict() for source in CURATED_TRADING_EDUCATION_SOURCES]
    concepts = [concept.to_dict() for concept in CURATED_TRADING_EDUCATION_CONCEPTS]
    by_status: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for source in sources:
        by_status[source["ingestion_status"]] = by_status.get(source["ingestion_status"], 0) + 1
        by_tier[source["tier"]] = by_tier.get(source["tier"], 0) + 1

    approved_seed_sources = [
        source
        for source in sources
        if source["ingestion_status"] in {"approved_seed", "approved_context_seed"}
    ]
    metadata_only = [
        source
        for source in sources
        if source["ingestion_status"] in {"metadata_only", "manual_review_only", "not_ingested"}
    ]

    return {
        "report_version": "trading_education_health_v1",
        "corpus_version": TRADING_EDUCATION_CORPUS_VERSION,
        "runtime_effect": TRADING_EDUCATION_RUNTIME_EFFECT,
        "authority_ready": False,
        "authority_note": "education corpus cannot approve, block, size, or execute trades",
        "source_count": len(sources),
        "concept_count": len(concepts),
        "approved_seed_count": len(approved_seed_sources),
        "metadata_or_manual_count": len(metadata_only),
        "approved_domains": sorted(approved_domains()),
        "by_status": dict(sorted(by_status.items())),
        "by_tier": dict(sorted(by_tier.items())),
        "sources": sources,
        "concepts": concepts,
    }
