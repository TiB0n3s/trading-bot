#!/usr/bin/env python3
"""
Automated company-news event collector.

No Claude. No trading. No paid APIs.

Fetches recent public news-search RSS headlines for approved symbols, classifies
headline/snippet text into structured event candidates, and returns event dicts
compatible with score_event() / daily_symbol_events.

This first version intentionally uses headline-level signals only. It does not
scrape full articles.
"""

from __future__ import annotations

import html
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

from symbols_config import (
    APPROVED_SYMBOLS,
    APPROVED_SYMBOLS_LIST,
    CONTEXT_ONLY_SYMBOL_CONFIG,
    EVENT_CONTEXT_SYMBOLS,
)

from market_intelligence.source_reliability import classify_source, normalize_source_name

logger = logging.getLogger(__name__)


# Use company/query names to reduce noisy ticker-only results.
# Especially important for short tickers like V, MA, BE, GE.
COMPANY_QUERY_NAMES = {
    "ADSK": "Autodesk",
    "BURL": "Burlington Stores",
    "DELL": "Dell Technologies",
    "DKS": "Dick's Sporting Goods",
    "MDB": "MongoDB",
    "NTAP": "NetApp",
    "OKTA": "Okta",
    "SNPS": "Synopsys",
    "ZS": "Zscaler",
    "AAPL": "Apple",
    "SPY": "SPDR S&P 500 ETF",
    "QQQ": "Invesco QQQ",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "ORCL": "Oracle",
    "TSCO": "Tractor Supply",
    "TSLA": "Tesla",
    "META": "Meta Platforms",
    "AMD": "Advanced Micro Devices",
    "CVX": "Chevron",
    "XOM": "Exxon Mobil",
    "GOOGL": "Alphabet Google",
    "GLD": "SPDR Gold Shares",
    "IWM": "iShares Russell 2000 ETF",
    "AVGO": "Broadcom",
    "CRDO": "Credo Technology",
    "GEV": "GE Vernova",
    "BE": "Bloom Energy",
    "CAT": "Caterpillar",
    "VRT": "Vertiv",
    "RKLB": "Rocket Lab",
    "RTX": "RTX Raytheon",
    "LMT": "Lockheed Martin",
    "HWM": "Howmet Aerospace",
    "VRTX": "Vertex Pharmaceuticals",
    "MRNA": "Moderna",
    "CRSP": "CRISPR Therapeutics",
    "V": "Visa",
    "MA": "Mastercard",
    "LLY": "Eli Lilly",
    "LIN": "Linde",
    "GE": "GE Aerospace",
    "ASML": "ASML",
    "NFLX": "Netflix",
    "CRM": "Salesforce",
    "COST": "Costco",
    "KO": "Coca-Cola",
    "ABBV": "AbbVie",
    "MRK": "Merck",
    "UNH": "UnitedHealth",
    "AMZN": "Amazon",
    "JPM": "JPMorgan Chase",
    "TSM": "Taiwan Semiconductor Manufacturing",
    "PYPL": "PayPal",
    "SOFI": "SoFi Technologies",
    "PFE": "Pfizer",
    "CMCSA": "Comcast",
    "T": "AT&T",
    "VZ": "Verizon",
    "F": "Ford Motor",
    "HBAN": "Huntington Bancshares",
    "KEY": "KeyCorp",
    "KHC": "Kraft Heinz",
}

for _symbol, _cfg in CONTEXT_ONLY_SYMBOL_CONFIG.items():
    COMPANY_QUERY_NAMES.setdefault(_symbol, _cfg.get("name", _symbol))


EVENT_KEYWORDS = [
    (
        "product_launch",
        [
            "launch",
            "launches",
            "launched",
            "unveils",
            "unveiled",
            "introduces",
            "introduced",
            "new product",
            "new device",
            "iphone",
            "ipad",
            "mac",
            "vision pro",
            "model",
            "release",
        ],
    ),
    (
        "earnings",
        [
            "earnings",
            "quarterly results",
            "q1",
            "q2",
            "q3",
            "q4",
            "revenue",
            "profit",
            "eps",
            "beat estimates",
            "misses estimates",
        ],
    ),
    (
        "guidance",
        [
            "guidance",
            "forecast",
            "outlook",
            "raises outlook",
            "cuts outlook",
            "raises forecast",
            "cuts forecast",
            "warns",
            "warning",
        ],
    ),
    (
        "analyst_action",
        [
            "upgrade",
            "downgrade",
            "price target",
            "initiates coverage",
            "maintains buy",
            "maintains sell",
            "overweight",
            "underweight",
        ],
    ),
    (
        "supply_chain",
        [
            "supply chain",
            "supplier",
            "suppliers",
            "shortage",
            "materials",
            "rare earth",
            "lithium",
            "chip supply",
            "semiconductor supply",
            "factory",
            "production halt",
            "export control",
            "tariff",
        ],
    ),
    (
        "supplier_signal",
        [
            "supplier",
            "suppliers",
            "supply agreement",
            "supplier agreement",
            "component",
            "components",
            "vendor",
            "manufacturing partner",
            "foundry",
            "contract manufacturer",
            "production partner",
        ],
    ),
    (
        "customer_contract",
        [
            "contract",
            "customer",
            "customers",
            "purchase agreement",
            "selected by",
            "awarded",
            "wins order",
            "large order",
            "backlog",
            "booking",
            "bookings",
        ],
    ),
    (
        "strategic_partnership",
        [
            "partnership",
            "partners with",
            "joint venture",
            "strategic collaboration",
            "strategic investment",
            "distribution agreement",
        ],
    ),
    (
        "leadership_personnel",
        [
            "ceo",
            "cfo",
            "chief executive",
            "chief financial",
            "resigns",
            "resignation",
            "steps down",
            "appointed",
            "names new",
            "hires",
        ],
    ),
    (
        "mna_deal_chatter",
        [
            "acquisition",
            "acquires",
            "merger",
            "takeover",
            "buyout",
            "deal talks",
            "explores sale",
            "strategic alternatives",
            "private equity",
            "stake sale",
            "backdoor deal",
        ],
    ),
    (
        "insider_transaction",
        [
            "insider buying",
            "insider bought",
            "insider purchase",
            "insider selling",
            "insider sold",
            "insider sale",
            "director bought",
            "director sold",
        ],
    ),
    (
        "congressional_trade_disclosure",
        [
            "congressional stock trade",
            "congressional trading",
            "stock act",
            "periodic transaction report",
            "public financial disclosure",
            "house disclosure",
            "senate disclosure",
            "senator bought",
            "senator sold",
            "representative bought",
            "representative sold",
            "politician bought",
            "politician sold",
            "lawmakers bought",
            "lawmakers sold",
            "quiver quantitative",
            "crypto daily",
            "cryptodaily",
        ],
    ),
    (
        "regulatory",
        [
            "regulator",
            "regulatory",
            "antitrust",
            "lawsuit",
            "sues",
            "probe",
            "investigation",
            "doj",
            "ftc",
            "sec",
            "eu",
            "fine",
            "ban",
            "sanction",
        ],
    ),
    (
        "competitive_threat",
        [
            "competition",
            "competitor",
            "rival",
            "pricing pressure",
            "market share",
            "discounts",
            "price cuts",
            "threat",
        ],
    ),
    (
        "ai_infrastructure_demand",
        [
            "ai demand",
            "artificial intelligence",
            "data center",
            "datacenter",
            "gpu",
            "accelerator",
            "ai infrastructure",
            "cloud capex",
            "capital spending",
        ],
    ),
    (
        "macro_geopolitical",
        [
            "fed",
            "inflation",
            "rates",
            "treasury yields",
            "war",
            "geopolitical",
            "china",
            "taiwan",
            "opec",
            "oil prices",
            "tariffs",
            "trade tensions",
        ],
    ),
    (
        "industry_demand",
        [
            "demand",
            "sales growth",
            "orders",
            "bookings",
            "shipments",
            "backlog",
            "consumer appetite",
            "strong sales",
        ],
    ),
]

EVENT_TYPE_PRIORITY = {
    "leadership_personnel": 1,
    "mna_deal_chatter": 2,
    "congressional_trade_disclosure": 3,
    "insider_transaction": 4,
    "customer_contract": 4,
    "strategic_partnership": 5,
    "supplier_signal": 6,
    "supply_chain": 7,
}


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def classify_event_type(text: str) -> tuple[str, str | None]:
    """Return (event_type, event_subtype)."""
    lowered = text.lower()

    scores = []
    for event_type, keywords in EVENT_KEYWORDS:
        hits = [kw for kw in keywords if kw in lowered]
        if hits:
            scores.append(
                (
                    len(hits),
                    -EVENT_TYPE_PRIORITY.get(event_type, 100),
                    event_type,
                    hits[0],
                )
            )

    if not scores:
        return "industry_demand", "headline_watch"

    scores.sort(reverse=True)
    _, _, event_type, first_hit = scores[0]
    return event_type, first_hit.replace(" ", "_")


def infer_time_horizon(event_type: str) -> str:
    if event_type in (
        "product_launch",
        "industry_demand",
        "ai_infrastructure_demand",
        "supplier_signal",
        "customer_contract",
        "strategic_partnership",
    ):
        return "weeks_to_quarters"
    if event_type in (
        "earnings",
        "guidance",
        "analyst_action",
        "leadership_personnel",
        "insider_transaction",
    ):
        return "days_to_weeks"
    if event_type in ("congressional_trade_disclosure",):
        return "delayed_disclosure_context"
    if event_type in ("regulatory", "supply_chain", "macro_geopolitical", "mna_deal_chatter"):
        return "weeks_to_months"
    return "days_to_weeks"


def rss_urls_for_symbol(symbol: str) -> list[tuple[str, str]]:
    name = COMPANY_QUERY_NAMES.get(symbol, symbol)
    # "when:1d" keeps results recent in Google News search syntax.
    base_query = f'("{name}" OR "{symbol}") stock when:1d'
    peripheral_query = (
        f'("{name}" OR "{symbol}") '
        "(supplier OR customer OR contract OR partnership OR acquisition OR merger "
        'OR CEO OR CFO OR insider OR "STOCK Act" OR "congressional trading" '
        'OR "periodic transaction report") stock when:3d'
    )
    return [
        (
            "company_direct",
            f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(base_query)}&hl=en-US&gl=US&ceid=US:en",
        ),
        (
            "company_peripheral",
            f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(peripheral_query)}&hl=en-US&gl=US&ceid=US:en",
        ),
    ]


def rss_url_for_symbol(symbol: str) -> str:
    return rss_urls_for_symbol(symbol)[0][1]


def fetch_rss_items(url: str, timeout: int = 12) -> list[dict]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 trading-bot-news-collector/1.0",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()

    root = ET.fromstring(raw)
    items = []

    for item in root.findall("./channel/item"):
        title = _clean_text(item.findtext("title"))
        link = _clean_text(item.findtext("link"))
        description = _clean_text(item.findtext("description"))
        pub_date_raw = _clean_text(item.findtext("pubDate"))

        published_at = None
        if pub_date_raw:
            try:
                published_at = parsedate_to_datetime(pub_date_raw).isoformat()
            except Exception:
                published_at = pub_date_raw

        items.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "published_at": published_at,
            }
        )

    return items


def publisher_from_google_news_title(title: str | None) -> str | None:
    if not title or " - " not in title:
        return None
    publisher = title.rsplit(" - ", 1)[-1].strip()
    return publisher or None


def _context_symbol_metadata(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    cfg = CONTEXT_ONLY_SYMBOL_CONFIG.get(symbol) or {}
    is_tradable = symbol in APPROVED_SYMBOLS
    return {
        "tradable": is_tradable,
        "context_only": not is_tradable,
        "linked_symbols": [
            str(s).upper()
            for s in (cfg.get("linked_symbols") or [])
            if str(s).upper() in APPROVED_SYMBOLS
        ],
        "relationship_type": cfg.get("relationship_type"),
        "relationship_themes": cfg.get("themes") or [],
        "context_symbol_universe": "approved" if is_tradable else "context_only",
    }


def event_from_item(
    market_date: str, symbol: str, item: dict, search_scope: str = "company_direct"
) -> dict:
    title = item.get("title") or ""
    desc = item.get("description") or ""
    text = f"{title}. {desc}".strip()

    event_type, subtype = classify_event_type(text)
    publisher = publisher_from_google_news_title(title)
    source_policy = classify_source(publisher, url=item.get("link"))
    source_name = source_policy["source_name"]

    return {
        "market_date": market_date,
        "symbol": symbol,
        "event_type": event_type,
        "event_subtype": subtype,
        "event_summary": title or desc[:220],
        # Google News RSS is the transport, not a reference source. If the
        # publisher cannot be extracted, keep the event low-confidence under an
        # explicit unknown-publisher source instead of crediting Google News.
        "source": source_name if source_name != "unknown" else "unknown_publisher",
        "source_url": item.get("link"),
        "time_horizon": infer_time_horizon(event_type),
        "confidence": "medium" if source_policy["trusted_source"] else "low",
        "collector": "google_news_rss",
        "search_scope": search_scope,
        "peripheral_context": search_scope == "company_peripheral",
        "publisher": normalize_source_name(publisher),
        **source_policy,
        "raw_collected_at": datetime.now().isoformat(timespec="seconds"),
        "raw_published_at": item.get("published_at"),
        "raw_headline": title,
        "raw_description": desc,
        **_context_symbol_metadata(symbol),
    }


def collect_company_news_events(
    market_date: str,
    symbols: list[str] | None = None,
    max_per_symbol: int = 3,
    timeout: int = 12,
) -> list[dict]:
    """Collect headline-derived event candidates for symbols."""
    symbols = symbols or APPROVED_SYMBOLS_LIST
    out = []

    for symbol in symbols:
        symbol = symbol.upper().strip()
        if symbol not in EVENT_CONTEXT_SYMBOLS:
            logger.warning("Skipping non-approved/non-context symbol: %s", symbol)
            continue

        seen_titles = set()
        added = 0

        for search_scope, url in rss_urls_for_symbol(symbol):
            try:
                items = fetch_rss_items(url, timeout=timeout)
            except Exception as e:
                logger.warning("News RSS fetch failed for %s scope=%s: %s", symbol, search_scope, e)
                continue

            for item in items:
                title = item.get("title") or ""
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)

                event = event_from_item(market_date, symbol, item, search_scope=search_scope)
                out.append(event)
                added += 1

                if added >= max_per_symbol:
                    break
            if added >= max_per_symbol:
                break

    return out


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol", action="append", help="Optional symbol filter; can repeat")
    parser.add_argument("--max-per-symbol", type=int, default=3)
    args = parser.parse_args()

    events = collect_company_news_events(
        market_date=args.date,
        symbols=args.symbol,
        max_per_symbol=args.max_per_symbol,
    )
    print(json.dumps(events, indent=2))
