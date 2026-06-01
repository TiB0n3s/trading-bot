"""Trusted source classification for market-intelligence events.

Collectors may use transports such as Google News RSS, but downstream event
context should reason about the original publisher or official source whenever
it is available.
"""

from __future__ import annotations

from urllib.parse import urlparse


SOURCE_POLICY_VERSION = "trusted_sources_v1"

OFFICIAL_SOURCES = {
    "sec",
    "sec edgar",
    "company investor relations",
    "company press release",
    "federal reserve",
    "bureau of labor statistics",
    "bea",
    "u.s. treasury",
    "census bureau",
    "eia",
    "nasdaq",
    "nyse",
    "cme",
    "ice",
    "cboe",
    "finra",
    "cftc",
}

HIGH_CONFIDENCE_NEWS = {
    "reuters",
    "bloomberg",
    "the wall street journal",
    "wall street journal",
    "wsj",
    "financial times",
    "ft",
    "cnbc",
    "marketwatch",
    "barron's",
    "barrons",
    "associated press",
    "ap business",
    "dow jones newswires",
    "dow jones",
}

DEEP_ANALYSIS_SOURCES = {
    "morningstar",
    "s&p global market intelligence",
    "s&p global",
    "the economist",
    "bloomberg opinion",
}

MEDIUM_CONFIDENCE_SOURCES = {
    "yahoo finance",
    "investing.com",
    "tradingview",
    "koyfin",
    "earnings whispers",
    "the information",
    "axios",
    "axios pro",
    "semafor",
    "seeking alpha",
    "pitchbook",
    "pe hub",
    "mergermarket",
    "dealreporter",
}

LOW_CONFIDENCE_SOURCES = {
    "x",
    "twitter",
    "reddit",
    "stocktwits",
    "discord",
    "telegram",
    "substack",
    "message board",
}

SOURCE_ALIASES = {
    "barrons": "barron's",
    "wsj": "the wall street journal",
    "ft": "financial times",
    "ap": "associated press",
    "ap news": "associated press",
    "sec.gov": "sec edgar",
    "federalreserve.gov": "federal reserve",
    "bls.gov": "bureau of labor statistics",
    "morningstar.com": "morningstar",
    "spglobal.com": "s&p global market intelligence",
}

DOMAIN_SOURCE_HINTS = {
    "reuters.com": "reuters",
    "bloomberg.com": "bloomberg",
    "wsj.com": "the wall street journal",
    "ft.com": "financial times",
    "cnbc.com": "cnbc",
    "marketwatch.com": "marketwatch",
    "barrons.com": "barron's",
    "apnews.com": "associated press",
    "morningstar.com": "morningstar",
    "spglobal.com": "s&p global market intelligence",
    "sec.gov": "sec edgar",
    "federalreserve.gov": "federal reserve",
    "bls.gov": "bureau of labor statistics",
    "nasdaq.com": "nasdaq",
    "nyse.com": "nyse",
    "cmegroup.com": "cme",
    "theice.com": "ice",
    "cboe.com": "cboe",
    "finra.org": "finra",
    "cftc.gov": "cftc",
    "finance.yahoo.com": "yahoo finance",
    "investing.com": "investing.com",
    "tradingview.com": "tradingview",
    "seekingalpha.com": "seeking alpha",
    "theinformation.com": "the information",
    "axios.com": "axios",
    "semafor.com": "semafor",
    "pitchbook.com": "pitchbook",
    "pehub.com": "pe hub",
    "twitter.com": "twitter",
    "x.com": "x",
    "reddit.com": "reddit",
    "stocktwits.com": "stocktwits",
}


def normalize_source_name(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "unknown"
    raw = raw.replace("’", "'")
    raw = " ".join(raw.split())
    return SOURCE_ALIASES.get(raw, raw)


def source_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None
    host = host[4:] if host.startswith("www.") else host
    for domain, source in DOMAIN_SOURCE_HINTS.items():
        if host == domain or host.endswith(f".{domain}"):
            return source
    return None


def classify_source(source: str | None = None, *, url: str | None = None) -> dict[str, str | bool]:
    source_name = normalize_source_name(source_from_url(url) or source)

    if source_name in OFFICIAL_SOURCES:
        tier = "official"
        reliability = "highest"
        trusted = True
    elif source_name in HIGH_CONFIDENCE_NEWS:
        tier = "confirmed_financial_news"
        reliability = "high"
        trusted = True
    elif source_name in DEEP_ANALYSIS_SOURCES:
        tier = "deep_analysis"
        reliability = "high"
        trusted = True
    elif source_name in MEDIUM_CONFIDENCE_SOURCES:
        tier = "medium_confidence"
        reliability = "medium"
        trusted = False
    elif source_name in LOW_CONFIDENCE_SOURCES:
        tier = "low_confidence"
        reliability = "low"
        trusted = False
    else:
        tier = "unclassified"
        reliability = "low"
        trusted = False

    return {
        "source_name": source_name,
        "source_tier": tier,
        "source_reliability": reliability,
        "trusted_source": trusted,
        "source_policy_version": SOURCE_POLICY_VERSION,
    }


def confidence_cap_for_sources(source_tiers: list[str] | tuple[str, ...], source_count: int) -> str:
    tiers = set(source_tiers or [])
    if "official" in tiers:
        return "official_source_high"
    trusted_tiers = {"confirmed_financial_news", "deep_analysis"}
    trusted_count = sum(1 for tier in source_tiers or [] if tier in trusted_tiers)
    if trusted_count >= 2:
        return "two_independent_reputable_sources"
    if trusted_count == 1:
        return "single_reputable_source_review"
    if source_count > 1:
        return "multi_source_untrusted_review"
    return "single_source_low"
