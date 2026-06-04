"""Curated trading education source contract.

This is intentionally a source-policy layer, not a scraper.  It defines what
the AI/ML education corpus may ingest or reference before any crawler is added.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from repositories.trading_education_repo import TradingEducationRepository


TRADING_EDUCATION_CORPUS_VERSION = "trading_education_corpus_v1"
TRADING_EDUCATION_RUNTIME_EFFECT = "education_context_only_no_trade_authority"
TRADING_EDUCATION_INGEST_VERSION = "trading_education_ingest_v1"
TRADING_EDUCATION_EXTRACTION_SCHEMA_VERSION = "trading_education_extraction_schema_v1"


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
    seed_urls: tuple[str, ...] = ()

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
        key="schwab_learn_trading",
        name="Charles Schwab Learn Trading",
        source_type="broker_education",
        tier="medium_education",
        url="https://www.schwab.com/learn/trading",
        topics=("trading_basics", "technical_analysis", "risk_management", "market_mechanics"),
        ingestion_status="approved_context_seed",
        link_follow_policy="same_domain_only",
        authority="education_context_only",
        notes="Broker education for trading concepts and mechanics. Not market-moving news or live authority.",
        seed_urls=(
            "https://www.schwab.com/learn/story/what-are-derivatives",
            "https://www.schwab.com/learn/story/options-strategy-covered-call",
            "https://www.schwab.com/learn/story/options-expiration-definitions-checklist-more",
            "https://www.schwab.com/learn/story/how-to-use-weekly-stock-options",
            "https://www.schwab.com/learn/story/what-happens-to-options-when-stock-splits",
            "https://www.schwab.com/learn/story/why-stocks-sometimes-ignore-good-or-bad-news",
            "https://www.schwab.com/learn/story/ins-and-outs-short-selling",
            "https://www.schwab.com/learn/story/ways-traders-spot-rallys-potential-end",
            "https://www.schwab.com/learn/story/aligning-your-options-with-implied-volatility",
            "https://www.schwab.com/learn/story/heikin-ashi-candles-reversals-and-strategies",
            "https://www.schwab.com/learn/story/pre-ipo-company-equity-6-actions-to-take-now",
        ),
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
    TradingEducationConcept(
        key="backtesting_overfitting_control",
        name="Backtesting and overfitting control",
        concept_type="governance",
        summary=(
            "Backtesting simulates clearly defined entry, exit, and risk rules on historical "
            "data, then evaluates profitability, drawdowns, robustness, and out-of-sample "
            "performance without risking capital."
        ),
        bot_usage=(
            "Use for promotion readiness, walk-forward validation, model drift review, "
            "policy replay, and report language around overfitting risk."
        ),
        live_authority="education_context_only",
        related_features=(
            "backtest_profit_factor",
            "max_drawdown",
            "walk_forward_window",
            "out_of_sample_score",
            "cross_validation_score",
            "parameter_count",
            "overfit_risk",
        ),
        guardrails=(
            "Do not promote a strategy from in-sample results alone.",
            "Prefer simple parameter sets and require walk-forward or out-of-sample validation.",
            "Treat high backtest performance with high parameter complexity as overfit risk.",
        ),
    ),
    TradingEducationConcept(
        key="news_expectations_positioning",
        name="News, expectations, and positioning",
        concept_type="market_behavior",
        summary=(
            "Stocks can move against apparently good or bad news when expectations, guidance, "
            "macro conditions, positioning, institutional flows, or buy-the-rumor/sell-the-news "
            "behavior matter more than the headline itself."
        ),
        bot_usage=(
            "Use for event-context validation, earnings reaction review, sell-the-news diagnostics, "
            "and post-trade explanations where headline sentiment diverges from price action."
        ),
        live_authority="education_context_only",
        related_features=(
            "expectation_gap",
            "priced_in_risk",
            "sell_the_news_risk",
            "guidance_vs_results",
            "institutional_flow_pressure",
            "macro_override",
            "positioning_imbalance",
        ),
        guardrails=(
            "Do not treat a positive headline as bullish without price/volume confirmation.",
            "Compare event interpretation against market reaction and prior expectations.",
        ),
    ),
    TradingEducationConcept(
        key="short_selling_risk",
        name="Short selling risk",
        concept_type="risk_management",
        summary=(
            "Short selling borrows and sells shares in expectation of a decline, but carries "
            "borrow availability, margin, short-squeeze, dividend, fee, and theoretically unlimited "
            "loss risks."
        ),
        bot_usage=(
            "Use for downside-asymmetry review, squeeze-risk labels, short-interest context, and "
            "guardrails around any future short/hedged strategy research."
        ),
        live_authority="education_context_only",
        related_features=(
            "short_interest",
            "borrow_cost",
            "locate_required",
            "short_squeeze_risk",
            "margin_call_risk",
            "gap_up_risk",
            "borrow_liquidity",
        ),
        guardrails=(
            "Do not introduce short execution authority without a separate broker/risk model.",
            "Treat short-sale education as risk context for long-only systems unless explicitly promoted.",
        ),
    ),
    TradingEducationConcept(
        key="rally_exhaustion_exit_patterns",
        name="Rally exhaustion and exit patterns",
        concept_type="exit_learning",
        summary=(
            "A rally may be losing durability when good news is sold, dip buyers stop being "
            "rewarded, price turns parabolic, closes occur near session lows, or bearish candle "
            "patterns confirm momentum deterioration."
        ),
        bot_usage=(
            "Use for exit-review labels, winner-became-loser diagnostics, peak-lock analysis, "
            "and post-trade explanations of missed scale-out opportunities."
        ),
        live_authority="education_context_only",
        related_features=(
            "bearish_engulfing",
            "dark_cloud_cover",
            "shooting_star",
            "three_black_crows",
            "advance_block",
            "rsi_negative_divergence",
            "parabolic_rise",
            "close_near_low",
            "down_volume_pressure",
        ),
        guardrails=(
            "Treat reversal patterns as corroborating evidence, not standalone exit authority.",
            "Require outcome attribution before promoting scale-out or exit-rule changes.",
        ),
    ),
    TradingEducationConcept(
        key="implied_volatility_context",
        name="Implied volatility context",
        concept_type="market_mechanics",
        summary=(
            "Implied volatility reflects option-market expectations for future move magnitude, "
            "not direction, and can be compared with historical volatility, event risk, VIX, and "
            "volatility rank or percentile."
        ),
        bot_usage=(
            "Use for event-risk context, expected-range telemetry, execution/risk explanations, "
            "and future options-aware volatility features."
        ),
        live_authority="education_context_only",
        related_features=(
            "implied_volatility",
            "historical_volatility",
            "iv_rank",
            "iv_percentile",
            "expected_move",
            "vix_context",
            "event_volatility_premium",
            "tail_risk",
        ),
        guardrails=(
            "Do not infer direction from implied volatility alone.",
            "Do not introduce options strategy authority without a separate options risk model.",
        ),
    ),
    TradingEducationConcept(
        key="heikin_ashi_trend_reversal",
        name="Heikin Ashi trend reversal context",
        concept_type="technical_analysis",
        summary=(
            "Heikin Ashi bars smooth candle noise by averaging current and prior bar data, "
            "helping identify trend persistence, choppy transitions, and possible reversals when "
            "used with confirmation such as EMA changes."
        ),
        bot_usage=(
            "Use for bar-pattern learning, trend deterioration labels, exit diagnostics, and "
            "candidate pattern explanations."
        ),
        live_authority="education_context_only",
        related_features=(
            "heikin_ashi_color_run",
            "heikin_ashi_wick_state",
            "heikin_ashi_body_size",
            "ema_8_21_cross",
            "trend_smoothing",
            "choppy_transition",
        ),
        guardrails=(
            "Heikin Ashi prices are derived averages and may not match executable prices.",
            "Expect signals to lag raw candles; use as context, not immediate execution authority.",
        ),
    ),
    TradingEducationConcept(
        key="ipo_liquidity_restrictions",
        name="IPO liquidity and insider restriction context",
        concept_type="event_risk",
        summary=(
            "IPO and pre-IPO equity events can involve S-1 disclosures, lock-up periods, blackout "
            "periods, trading windows, 10b5-1 plans, dilution risk, concentration risk, taxes, and "
            "post-listing volatility."
        ),
        bot_usage=(
            "Use for IPO/event context, insider-supply risk, lock-up expiration review, and "
            "peripheral company intelligence explanations."
        ),
        live_authority="education_context_only",
        related_features=(
            "ipo_event",
            "s1_filing",
            "lockup_expiration",
            "blackout_period",
            "trading_window",
            "10b5_1_plan",
            "dilution_risk",
            "insider_supply_risk",
            "concentration_risk",
        ),
        guardrails=(
            "Use official filings as source of truth for company-specific IPO or insider details.",
            "Do not treat employee-equity education as directional market evidence.",
        ),
    ),
    TradingEducationConcept(
        key="algorithmic_trading_pipeline",
        name="Algorithmic trading pipeline design",
        concept_type="system_design",
        summary=(
            "A market-prediction system should define objective, asset universe, timeframe, and "
            "strategy hypothesis; ingest clean OHLCV and contextual data; engineer features; select "
            "models appropriate to the task; run leakage-safe backtests with realistic frictions; "
            "enforce risk controls; and validate forward behavior in paper trading before live use."
        ),
        bot_usage=(
            "Use for ML roadmap checks, training pipeline reviews, model-readiness explanations, "
            "data-quality diagnostics, and deployment guardrail language."
        ),
        live_authority="education_context_only",
        related_features=(
            "asset_universe",
            "trading_timeframe",
            "strategy_hypothesis",
            "ohlcv_quality",
            "alternative_data_context",
            "technical_indicator_set",
            "data_leakage_guard",
            "transaction_cost_model",
            "slippage_model",
            "max_drawdown",
            "sharpe_ratio",
            "win_loss_ratio",
            "position_sizing",
            "portfolio_diversification",
            "paper_trading_duration",
            "latency_monitoring",
        ),
        guardrails=(
            "Do not treat model architecture choice as evidence of profitability.",
            "Require leakage-safe backtesting, friction modeling, and forward paper results before promotion.",
            "Keep hard risk controls independent of predictive model confidence.",
        ),
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


class _EducationHtmlExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self._capture_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if lower == "title":
            self._capture_title = True
        if lower == "a":
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if lower == "title":
            self._capture_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join((data or "").split())
        if not text or self._skip_depth:
            return
        if self._capture_title:
            self.title_parts.append(text)
        elif len(text) > 2:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        return " ".join(self.text_parts).strip()


def _normalize_text(text: str, *, max_chars: int = 20000) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    return normalized[:max_chars]


def _compact_summary(text: str, *, max_chars: int = 700) -> str:
    text = _normalize_text(text, max_chars=6000)
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(sentence for sentence in sentences[:4] if sentence).strip()
    return summary[:max_chars]


def _guess_title_from_text(text: str, fallback: str) -> str:
    for line in (text or "").splitlines():
        clean = " ".join(line.split()).strip()
        if len(clean) >= 8:
            return clean[:300]
    return fallback


def _concept_matches(text: str) -> tuple[list[str], list[str]]:
    lower = f" {text.lower()} "
    concept_keys: list[str] = []
    related_features: set[str] = set()
    keyword_map = {
        "trend_trading": ("trend", "moving average", "higher high", "continuation"),
        "range_trading": ("range", "support", "resistance", "mean reversion"),
        "breakout_trading": ("breakout", "break out", "volume expansion", "new high"),
        "reversal_trading": ("reversal", "trend break", "pullback", "retracement"),
        "gap_trading": ("gap", "opening range", "gap up", "gap down"),
        "pairs_trading": ("pairs", "relative strength", "correlation", "spread"),
        "arbitrage": ("arbitrage", "dislocation", "price difference"),
        "momentum_trading": ("momentum", "volume", "force index", "price volume trend", "vwap"),
        "risk_practice_before_live": (
            "risk",
            "risks",
            "paper",
            "simulator",
            "practice",
            "diversification",
            "derivatives",
            "options",
            "covered call",
            "expiration",
            "weekly options",
            "stock splits",
            "leverage",
            "assignment",
            "liquidity",
            "contract",
            "manage risk",
        ),
        "strategy_vs_style": (
            "strategy",
            "strategies",
            "trading style",
            "investment style",
            "covered call strategy",
            "options strategy",
        ),
        "backtesting_overfitting_control": (
            "backtest",
            "backtesting",
            "walk-forward",
            "walk forward",
            "cross-validation",
            "out-of-sample",
            "out of sample",
            "overfit",
            "overfitting",
            "drawdown",
        ),
        "news_expectations_positioning": (
            "already priced in",
            "forward guidance",
            "earnings call",
            "sell the news",
            "buy the rumor",
            "positioning",
            "institutional flows",
            "tax-loss harvesting",
            "investor sentiment may be turning",
            "headline sentiment",
            "ignore good",
            "ignore bad",
        ),
        "short_selling_risk": (
            "short selling",
            "short sale",
            "short-sellers",
            "short squeeze",
            "borrow shares",
            "borrowed shares",
            "naked shorting",
            "locate",
            "buy-stop",
            "trailing buy-stop",
            "dividend payments",
            "potentially limitless losses",
        ),
        "rally_exhaustion_exit_patterns": (
            "rally's potential end",
            "rally may be coming to an end",
            "good news is bad news",
            "dip buyers stop",
            "sharp top",
            "parabolic",
            "closes near the day's lows",
            "bearish engulfing",
            "dark cloud cover",
            "shooting star",
            "three black crows",
            "advance block",
            "negative divergence",
        ),
        "implied_volatility_context": (
            "implied volatility",
            "historical volatility",
            "iv rank",
            "iv percentile",
            "probability cone",
            "expected volatility",
            "expected move",
            "vix",
            "short vega",
            "long vega",
            "term structure",
            "tail risk",
        ),
        "heikin_ashi_trend_reversal": (
            "heikin ashi",
            "heiken ashi",
            "average bar",
            "heikin ashi bar",
            "short-range bars",
            "without bottom wicks",
            "ema crossed",
            "eight-period ema",
            "21-period ema",
        ),
        "ipo_liquidity_restrictions": (
            "pre-ipo",
            "initial public offering",
            "s-1",
            "lock-up period",
            "lockup period",
            "blackout period",
            "trading window",
            "10b5-1",
            "tender offer",
            "equity incentive plan",
            "award agreement",
            "dilution",
            "concentration risk",
        ),
        "algorithmic_trading_pipeline": (
            "algorithmic system",
            "market trends",
            "asset classes",
            "establish timeframes",
            "formulate hypotheses",
            "ohlcv",
            "alternative data",
            "technical indicators",
            "moving averages",
            "relative strength index",
            "bollinger bands",
            "predictive model architecture",
            "arima",
            "garch",
            "xgboost",
            "lstm",
            "transformers",
            "finbert",
            "backtesting engine",
            "data leakage",
            "transactional variables",
            "sharpe ratio",
            "maximum drawdown",
            "win/loss ratio",
            "position sizing",
            "kelly criterion",
            "portfolio diversification",
            "paper trading",
            "system latency",
        ),
    }
    concept_lookup = {concept.key: concept for concept in CURATED_TRADING_EDUCATION_CONCEPTS}
    for key, terms in keyword_map.items():
        if any(term in lower for term in terms):
            concept_keys.append(key)
            related_features.update(concept_lookup[key].related_features)
    return sorted(set(concept_keys)), sorted(related_features)


def _same_domain(base_url: str, candidate_url: str) -> bool:
    base = urlparse(base_url)
    candidate = urlparse(candidate_url)
    base_host = base.netloc.lower()[4:] if base.netloc.lower().startswith("www.") else base.netloc.lower()
    candidate_host = (
        candidate.netloc.lower()[4:]
        if candidate.netloc.lower().startswith("www.")
        else candidate.netloc.lower()
    )
    return bool(candidate.scheme in {"http", "https"} and candidate_host == base_host)


def _blocked_or_error_page(title: str, text: str) -> str | None:
    combined = f"{title} {text}".lower()
    if "unable to authorize your request" in combined:
        return "authorization_error_page"
    if "access denied" in combined or "forbidden" in combined:
        return "access_denied_page"
    if title.strip().lower() == "charles schwab" and "we apologize for any inconvenience" in combined:
        return "schwab_authorization_error_page"
    return None


def _confidence_and_warnings(
    *,
    title: str,
    text: str,
    concept_keys: list[str],
    source: TradingEducationSource,
    ingestion_method: str,
) -> tuple[float, list[str], str]:
    warnings: list[str] = []
    text_len = len(text or "")
    if text_len < 250:
        warnings.append("short_text")
    if not concept_keys:
        warnings.append("no_concept_match")
    if source.tier.startswith("official"):
        base = 0.8
    elif source.tier in {"medium_education", "official_high"}:
        base = 0.68
    else:
        base = 0.55
    if ingestion_method == "manual_snapshot":
        base -= 0.08
    if text_len >= 1000:
        base += 0.08
    elif text_len >= 500:
        base += 0.04
    if concept_keys:
        base += 0.08
    if not title or title == source.name:
        warnings.append("generic_or_missing_title")
        base -= 0.05
    confidence = max(0.0, min(0.99, round(base, 4)))
    status = "stored" if confidence >= 0.55 and not warnings else "needs_review"
    if warnings == ["generic_or_missing_title"] and confidence >= 0.6:
        status = "stored"
    return confidence, warnings, status


class TradingEducationIngestionService:
    """Bounded crawler/extractor for approved education sources.

    The output is compact concept metadata. It is intentionally not a market
    signal and cannot alter live approval, sizing, or execution behavior.
    """

    def __init__(
        self,
        *,
        repo: TradingEducationRepository | None = None,
        timeout_seconds: float = 8.0,
        user_agent: str = "trading-bot education-corpus/1.0",
        transport: Any | None = None,
    ):
        self.repo = repo or TradingEducationRepository()
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.transport = transport or self._default_transport

    def _default_transport(self, url: str) -> str:
        req = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as response:
            raw = response.read(1_000_000)
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def approved_sources() -> list[TradingEducationSource]:
        return [
            source
            for source in CURATED_TRADING_EDUCATION_SOURCES
            if source.url and source.ingestion_status in {"approved_seed", "approved_context_seed"}
        ]

    @classmethod
    def approved_seed_pairs(cls) -> list[tuple[TradingEducationSource, str]]:
        pairs: list[tuple[TradingEducationSource, str]] = []
        for source in cls.approved_sources():
            if source.url:
                pairs.append((source, source.url))
            for url in source.seed_urls:
                if source.url and _same_domain(source.url, url):
                    pairs.append((source, url))
        return pairs

    def _store_failure(self, source: TradingEducationSource, url: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.repo.upsert_page(
            {
                "source_key": source.key,
                "source_name": source.name,
                "source_tier": source.tier,
                "url": url,
                "title": None,
                "retrieved_at": now,
                "content_hash": hashlib.sha256(error.encode("utf-8")).hexdigest(),
                "summary": None,
                "concept_keys": "[]",
                "related_features": "[]",
                "source_policy_version": TRADING_EDUCATION_CORPUS_VERSION,
                "corpus_version": TRADING_EDUCATION_CORPUS_VERSION,
                "runtime_effect": TRADING_EDUCATION_RUNTIME_EFFECT,
                "status": "fetch_failed",
                "error": error[:500],
                "extraction_confidence": 0.0,
                "extraction_warnings": json.dumps(["fetch_failed"], sort_keys=True),
                "ingestion_method": "fetch",
            }
        )

    def _extract_page(
        self,
        source: TradingEducationSource,
        url: str,
        html: str,
        *,
        ingestion_method: str = "fetch",
    ) -> dict[str, Any]:
        parser = _EducationHtmlExtractor()
        parser.feed(html)
        text = _normalize_text(parser.text)
        title = parser.title or _guess_title_from_text(text, source.name)
        blocked_reason = _blocked_or_error_page(title, text)
        if blocked_reason:
            raise RuntimeError(blocked_reason)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        concept_keys, related_features = _concept_matches(f"{title} {text}")
        confidence, warnings, status = _confidence_and_warnings(
            title=title,
            text=text,
            concept_keys=concept_keys,
            source=source,
            ingestion_method=ingestion_method,
        )
        now = datetime.now(timezone.utc).isoformat()
        return {
            "source_key": source.key,
            "source_name": source.name,
            "source_tier": source.tier,
            "url": url,
            "title": title[:300],
            "retrieved_at": now,
            "content_hash": content_hash,
            "summary": _compact_summary(text),
            "concept_keys": json.dumps(concept_keys, sort_keys=True),
            "related_features": json.dumps(related_features, sort_keys=True),
            "source_policy_version": TRADING_EDUCATION_CORPUS_VERSION,
            "corpus_version": TRADING_EDUCATION_CORPUS_VERSION,
            "runtime_effect": TRADING_EDUCATION_RUNTIME_EFFECT,
            "status": status,
            "error": None,
            "extraction_confidence": confidence,
            "extraction_warnings": json.dumps(warnings, sort_keys=True) if warnings else None,
            "ingestion_method": ingestion_method,
            "_links": [
                urljoin(url, link)
                for link in parser.links
                if _same_domain(url, urljoin(url, link))
            ],
        }

    def ingest(
        self,
        *,
        max_pages: int = 12,
        follow_links: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        self.repo.init_table()
        queue: list[tuple[TradingEducationSource, str]] = self.approved_seed_pairs()
        seen: set[str] = set()
        stored = 0
        needs_review = 0
        failed = 0
        visited: list[dict[str, Any]] = []

        while queue and len(seen) < max_pages:
            source, url = queue.pop(0)
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                html = self.transport(url)
                row = self._extract_page(source, url, html)
                links = row.pop("_links", [])
                if not dry_run:
                    self.repo.upsert_page(row)
                if row["status"] == "stored":
                    stored += 1
                elif row["status"] == "needs_review":
                    needs_review += 1
                visited.append({"url": url, "source_key": source.key, "status": row["status"]})
                if follow_links:
                    for link in links[:5]:
                        if link not in seen and len(queue) + len(seen) < max_pages * 2:
                            queue.append((source, link))
            except Exception as exc:
                failed += 1
                if not dry_run:
                    self._store_failure(source, url, str(exc))
                visited.append({"url": url, "source_key": source.key, "status": "fetch_failed", "error": str(exc)})

        return {
            "report_version": "trading_education_ingest_report_v1",
            "ingest_version": TRADING_EDUCATION_INGEST_VERSION,
            "corpus_version": TRADING_EDUCATION_CORPUS_VERSION,
            "runtime_effect": TRADING_EDUCATION_RUNTIME_EFFECT,
            "dry_run": dry_run,
            "visited": len(visited),
            "stored": stored,
            "needs_review": needs_review,
            "failed": failed,
            "max_pages": max_pages,
            "follow_links": follow_links,
            "pages": visited,
            "repository_summary": self.repo.summary() if not dry_run else {},
        }

    @staticmethod
    def source_for_url(url: str) -> TradingEducationSource | None:
        if not classify_education_url(url).get("matched"):
            return None
        host = urlparse(url or "").netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        for source in CURATED_TRADING_EDUCATION_SOURCES:
            if not source.url:
                continue
            source_host = urlparse(source.url).netloc.lower()
            source_host = source_host[4:] if source_host.startswith("www.") else source_host
            if host == source_host or host.endswith(f".{source_host}"):
                return source
        return None

    def ingest_manual_snapshot(
        self,
        *,
        url: str,
        content: str,
        title: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        source = self.source_for_url(url)
        if source is None:
            return {
                "report_version": "trading_education_manual_ingest_v1",
                "corpus_version": TRADING_EDUCATION_CORPUS_VERSION,
                "runtime_effect": TRADING_EDUCATION_RUNTIME_EFFECT,
                "status": "blocked",
                "url": url,
                "error": "url_not_in_approved_education_sources",
            }
        body = content or ""
        html = (
            f"<html><head><title>{title or ''}</title></head><body><pre>{body}</pre></body></html>"
            if "<html" not in body.lower()
            else body
        )
        row = self._extract_page(source, url, html, ingestion_method="manual_snapshot")
        if title:
            row["title"] = title[:300]
        row.pop("_links", None)
        if not dry_run:
            self.repo.upsert_page(row)
        return {
            "report_version": "trading_education_manual_ingest_v1",
            "schema_version": TRADING_EDUCATION_EXTRACTION_SCHEMA_VERSION,
            "corpus_version": TRADING_EDUCATION_CORPUS_VERSION,
            "runtime_effect": TRADING_EDUCATION_RUNTIME_EFFECT,
            "status": row["status"],
            "url": url,
            "source_key": source.key,
            "title": row["title"],
            "concept_keys": json.loads(row["concept_keys"] or "[]"),
            "related_features": json.loads(row["related_features"] or "[]"),
            "extraction_confidence": row["extraction_confidence"],
            "extraction_warnings": json.loads(row["extraction_warnings"] or "[]"),
            "dry_run": dry_run,
        }

    def ingest_manual_file(
        self,
        *,
        url: str,
        path: Path | str,
        title: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        file_path = Path(path)
        content = file_path.read_text(errors="replace")
        return self.ingest_manual_snapshot(
            url=url,
            content=content,
            title=title,
            dry_run=dry_run,
        )
