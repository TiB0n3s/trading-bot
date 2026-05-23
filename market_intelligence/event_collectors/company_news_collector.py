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

from symbols_config import APPROVED_SYMBOLS_LIST

logger = logging.getLogger(__name__)


# Use company/query names to reduce noisy ticker-only results.
# Especially important for short tickers like V, MA, BE, GE.
COMPANY_QUERY_NAMES = {
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
}


EVENT_KEYWORDS = [
    (
        "product_launch",
        [
            "launch", "launches", "launched", "unveils", "unveiled",
            "introduces", "introduced", "new product", "new device",
            "iphone", "ipad", "mac", "vision pro", "model", "release",
        ],
    ),
    (
        "earnings",
        [
            "earnings", "quarterly results", "q1", "q2", "q3", "q4",
            "revenue", "profit", "eps", "beat estimates", "misses estimates",
        ],
    ),
    (
        "guidance",
        [
            "guidance", "forecast", "outlook", "raises outlook", "cuts outlook",
            "raises forecast", "cuts forecast", "warns", "warning",
        ],
    ),
    (
        "analyst_action",
        [
            "upgrade", "downgrade", "price target", "initiates coverage",
            "maintains buy", "maintains sell", "overweight", "underweight",
        ],
    ),
    (
        "supply_chain",
        [
            "supply chain", "supplier", "suppliers", "shortage", "materials",
            "rare earth", "lithium", "chip supply", "semiconductor supply",
            "factory", "production halt", "export control", "tariff",
        ],
    ),
    (
        "regulatory",
        [
            "regulator", "regulatory", "antitrust", "lawsuit", "sues",
            "probe", "investigation", "doj", "ftc", "sec", "eu", "fine",
            "ban", "sanction",
        ],
    ),
    (
        "competitive_threat",
        [
            "competition", "competitor", "rival", "pricing pressure",
            "market share", "discounts", "price cuts", "threat",
        ],
    ),
    (
        "ai_infrastructure_demand",
        [
            "ai demand", "artificial intelligence", "data center", "datacenter",
            "gpu", "accelerator", "ai infrastructure", "cloud capex",
            "capital spending",
        ],
    ),
    (
        "macro_geopolitical",
        [
            "fed", "inflation", "rates", "treasury yields", "war",
            "geopolitical", "china", "taiwan", "opec", "oil prices",
            "tariffs", "trade tensions",
        ],
    ),
    (
        "industry_demand",
        [
            "demand", "sales growth", "orders", "bookings", "shipments",
            "backlog", "consumer appetite", "strong sales",
        ],
    ),
]


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
            scores.append((len(hits), event_type, hits[0]))

    if not scores:
        return "industry_demand", "headline_watch"

    scores.sort(reverse=True)
    _, event_type, first_hit = scores[0]
    return event_type, first_hit.replace(" ", "_")


def infer_time_horizon(event_type: str) -> str:
    if event_type in ("product_launch", "industry_demand", "ai_infrastructure_demand"):
        return "weeks_to_quarters"
    if event_type in ("earnings", "guidance", "analyst_action"):
        return "days_to_weeks"
    if event_type in ("regulatory", "supply_chain", "macro_geopolitical"):
        return "weeks_to_months"
    return "days_to_weeks"


def rss_url_for_symbol(symbol: str) -> str:
    name = COMPANY_QUERY_NAMES.get(symbol, symbol)
    # "when:1d" keeps results recent in Google News search syntax.
    query = f'("{name}" OR "{symbol}") stock when:1d'
    encoded = urllib.parse.quote_plus(query)
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


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

        items.append({
            "title": title,
            "link": link,
            "description": description,
            "published_at": published_at,
        })

    return items


def event_from_item(market_date: str, symbol: str, item: dict) -> dict:
    title = item.get("title") or ""
    desc = item.get("description") or ""
    text = f"{title}. {desc}".strip()

    event_type, subtype = classify_event_type(text)

    return {
        "market_date": market_date,
        "symbol": symbol,
        "event_type": event_type,
        "event_subtype": subtype,
        "event_summary": title or desc[:220],
        "source": "google_news_rss",
        "source_url": item.get("link"),
        "time_horizon": infer_time_horizon(event_type),
        "confidence": "low",
        "raw_collected_at": datetime.now().isoformat(timespec="seconds"),
        "raw_published_at": item.get("published_at"),
        "raw_headline": title,
        "raw_description": desc,
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
        if symbol not in APPROVED_SYMBOLS_LIST:
            logger.warning("Skipping non-approved symbol: %s", symbol)
            continue

        url = rss_url_for_symbol(symbol)
        try:
            items = fetch_rss_items(url, timeout=timeout)
        except Exception as e:
            logger.warning("News RSS fetch failed for %s: %s", symbol, e)
            continue

        seen_titles = set()
        added = 0

        for item in items:
            title = item.get("title") or ""
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)

            event = event_from_item(market_date, symbol, item)
            out.append(event)
            added += 1

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
