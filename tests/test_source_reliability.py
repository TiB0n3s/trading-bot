#!/usr/bin/env python3
"""Tests for trusted event-source classification."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from market_intelligence.event_collectors.company_news_collector import (
    classify_event_type,
    event_from_item,
    publisher_from_google_news_title,
    rss_urls_for_symbol,
)
from market_intelligence.source_reliability import (
    classify_source,
    confidence_cap_for_sources,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_classifies_official_and_top_tier_sources():
    sec = classify_source("SEC")
    reuters = classify_source("Reuters")
    yahoo = classify_source("Yahoo Finance")
    social = classify_source("StockTwits")

    assert_equal(sec["source_tier"], "official", "SEC tier")
    assert_equal(sec["trusted_source"], True, "SEC trusted")
    assert_equal(reuters["source_tier"], "confirmed_financial_news", "Reuters tier")
    assert_equal(reuters["trusted_source"], True, "Reuters trusted")
    assert_equal(yahoo["source_tier"], "medium_confidence", "Yahoo tier")
    assert_equal(yahoo["trusted_source"], False, "Yahoo trusted")
    assert_equal(social["source_tier"], "low_confidence", "social tier")


def test_classifies_source_from_url_when_available():
    result = classify_source(url="https://www.reuters.com/markets/deals/example")

    assert_equal(result["source_name"], "reuters", "source name")
    assert_equal(result["source_reliability"], "high", "reliability")


def test_classifies_cryptodaily_as_trusted_government_trading_reference():
    named = classify_source("Crypto Daily")
    domain = classify_source(url="https://cryptodaily.co.uk/news/example")

    assert_equal(named["source_name"], "crypto daily", "named source")
    assert_equal(named["source_tier"], "deep_analysis", "named tier")
    assert_equal(named["trusted_source"], True, "named trusted")
    assert_equal(domain["source_name"], "crypto daily", "domain source")
    assert_equal(domain["source_tier"], "deep_analysis", "domain tier")
    assert_equal(domain["trusted_source"], True, "domain trusted")


def test_classifies_public_disclosure_sources():
    house = classify_source(url="https://disclosures-clerk.house.gov/FinancialDisclosure")
    senate = classify_source(url="https://efdsearch.senate.gov/search/")
    quiver = classify_source("Quiver Quantitative")

    assert_equal(house["source_tier"], "official", "House disclosure tier")
    assert_equal(house["trusted_source"], True, "House disclosure trusted")
    assert_equal(senate["source_tier"], "official", "Senate disclosure tier")
    assert_equal(senate["trusted_source"], True, "Senate disclosure trusted")
    assert_equal(quiver["source_tier"], "medium_confidence", "Quiver tier")
    assert_equal(quiver["trusted_source"], False, "Quiver trusted")


def test_google_news_publisher_becomes_event_source_of_record():
    item = {
        "title": "Apple shares rise on product demand - Reuters",
        "link": "https://news.google.com/rss/articles/example",
        "description": "Apple demand improved.",
        "published_at": "2026-06-01T12:00:00+00:00",
    }

    event = event_from_item("2026-06-01", "AAPL", item)

    assert_equal(publisher_from_google_news_title(item["title"]), "Reuters", "publisher")
    assert_equal(event["collector"], "google_news_rss", "collector")
    assert_equal(event["source"], "reuters", "source")
    assert_equal(event["source_tier"], "confirmed_financial_news", "tier")
    assert_equal(event["trusted_source"], True, "trusted")
    assert_equal(event["confidence"], "medium", "confidence")


def test_google_news_transport_is_not_used_as_source_when_publisher_unknown():
    item = {
        "title": "Apple shares rise on product demand",
        "link": "https://news.google.com/rss/articles/example",
        "description": "Apple demand improved.",
        "published_at": "2026-06-01T12:00:00+00:00",
    }

    event = event_from_item("2026-06-01", "AAPL", item)

    assert_equal(event["collector"], "google_news_rss", "collector")
    assert_equal(event["source"], "unknown_publisher", "source")
    assert_equal(event["source_tier"], "unclassified", "tier")
    assert_equal(event["trusted_source"], False, "trusted")


def test_context_only_symbol_is_marked_non_tradable_and_linked():
    item = {
        "title": "Micron memory demand improves for AI suppliers - Reuters",
        "link": "https://news.google.com/rss/articles/example",
        "description": "Memory demand improved.",
        "published_at": "2026-06-01T12:00:00+00:00",
    }

    event = event_from_item("2026-06-01", "MU", item)

    assert_equal(event["symbol"], "MU", "symbol")
    assert_equal(event["tradable"], False, "tradable")
    assert_equal(event["context_only"], True, "context only")
    assert "NVDA" in event["linked_symbols"]
    assert "AMD" in event["linked_symbols"]
    assert_equal(event["context_symbol_universe"], "context_only", "universe")


def test_peripheral_scope_is_preserved_on_collected_event():
    item = {
        "title": "Apple CFO resigns as supplier contract is reviewed - Reuters",
        "link": "https://news.google.com/rss/articles/example",
        "description": "Leadership and supplier context changed.",
        "published_at": "2026-06-01T12:00:00+00:00",
    }

    event = event_from_item(
        "2026-06-01",
        "AAPL",
        item,
        search_scope="company_peripheral",
    )

    assert_equal(event["search_scope"], "company_peripheral", "search scope")
    assert_equal(event["peripheral_context"], True, "peripheral context")
    assert event["event_type"] in {
        "leadership_personnel",
        "supplier_signal",
        "customer_contract",
    }


def test_symbol_has_direct_and_peripheral_news_queries():
    urls = rss_urls_for_symbol("AAPL")

    assert_equal([scope for scope, _ in urls], ["company_direct", "company_peripheral"], "scopes")
    assert "supplier" in urls[1][1].lower()
    assert "cfo" in urls[1][1].lower()


def test_classifies_peripheral_event_types():
    event_type, _ = classify_event_type("CEO resigns after supplier shortage")

    assert event_type in {"leadership_personnel", "supplier_signal"}


def test_classifies_congressional_trade_disclosure_event_type():
    event_type, _ = classify_event_type(
        "Senator filed a periodic transaction report under the STOCK Act after buying NVDA"
    )

    assert_equal(event_type, "congressional_trade_disclosure", "event type")


def test_cryptodaily_reference_can_classify_government_trading_event():
    event_type, _ = classify_event_type(
        "CryptoDaily coverage tracks congressional trading and government crypto disclosures"
    )

    assert_equal(event_type, "congressional_trade_disclosure", "event type")


def test_confidence_cap_prefers_official_and_two_reputable_sources():
    assert_equal(
        confidence_cap_for_sources(["official"], 1),
        "official_source_high",
        "official cap",
    )
    assert_equal(
        confidence_cap_for_sources(
            ["confirmed_financial_news", "deep_analysis"],
            2,
        ),
        "two_independent_reputable_sources",
        "two trusted cap",
    )
    assert_equal(
        confidence_cap_for_sources(["confirmed_financial_news"], 1),
        "single_reputable_source_review",
        "one trusted cap",
    )
    assert_equal(
        confidence_cap_for_sources(["medium_confidence", "unclassified"], 2),
        "multi_source_untrusted_review",
        "untrusted multi-source cap",
    )


def main():
    tests = [
        test_classifies_official_and_top_tier_sources,
        test_classifies_source_from_url_when_available,
        test_classifies_cryptodaily_as_trusted_government_trading_reference,
        test_classifies_public_disclosure_sources,
        test_google_news_publisher_becomes_event_source_of_record,
        test_google_news_transport_is_not_used_as_source_when_publisher_unknown,
        test_context_only_symbol_is_marked_non_tradable_and_linked,
        test_peripheral_scope_is_preserved_on_collected_event,
        test_symbol_has_direct_and_peripheral_news_queries,
        test_classifies_peripheral_event_types,
        test_classifies_congressional_trade_disclosure_event_type,
        test_cryptodaily_reference_can_classify_government_trading_event,
        test_confidence_cap_prefers_official_and_two_reputable_sources,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} source reliability tests passed.")


if __name__ == "__main__":
    main()
