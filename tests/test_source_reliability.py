#!/usr/bin/env python3
"""Tests for trusted event-source classification."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_intelligence.event_collectors.company_news_collector import (
    event_from_item,
    publisher_from_google_news_title,
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
        test_google_news_publisher_becomes_event_source_of_record,
        test_google_news_transport_is_not_used_as_source_when_publisher_unknown,
        test_confidence_cap_prefers_official_and_two_reputable_sources,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} source reliability tests passed.")


if __name__ == "__main__":
    main()
