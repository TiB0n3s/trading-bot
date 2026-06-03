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
        "approved_seed_count": len(approved_seed_sources),
        "metadata_or_manual_count": len(metadata_only),
        "approved_domains": sorted(approved_domains()),
        "by_status": dict(sorted(by_status.items())),
        "by_tier": dict(sorted(by_tier.items())),
        "sources": sources,
    }
