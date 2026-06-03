#!/usr/bin/env python3
"""Tests for curated trading education source policy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.trading_education_corpus_service import (  # noqa: E402
    TRADING_EDUCATION_RUNTIME_EFFECT,
    approved_domains,
    build_trading_education_health_payload,
    classify_education_url,
)


def test_trading_education_payload_is_non_authoritative_and_versioned():
    payload = build_trading_education_health_payload()

    assert payload["report_version"] == "trading_education_health_v1"
    assert payload["runtime_effect"] == TRADING_EDUCATION_RUNTIME_EFFECT
    assert payload["authority_ready"] is False
    assert payload["approved_seed_count"] >= 6
    assert "investor.gov" in payload["approved_domains"]
    assert "investopedia.com" in payload["approved_domains"]


def test_classify_education_url_allows_only_curated_domains():
    sec = classify_education_url("https://www.investor.gov/introduction-investing")
    investopedia = classify_education_url("https://www.investopedia.com/terms/v/vwap.asp")
    unknown = classify_education_url("https://example.com/trading-course")

    assert sec["matched"] is True
    assert sec["tier"] == "official_highest"
    assert sec["link_follow_policy"] == "same_domain_only"
    assert investopedia["matched"] is True
    assert investopedia["ingestion_status"] == "approved_context_seed"
    assert unknown["matched"] is False
    assert unknown["ingestion_status"] == "blocked"


def test_books_and_heuristics_are_not_crawl_domains():
    domains = approved_domains()

    assert "ricedelman.com" not in domains
    assert all("graham" not in domain for domain in domains)


def main():
    tests = [
        test_trading_education_payload_is_non_authoritative_and_versioned,
        test_classify_education_url_allows_only_curated_domains,
        test_books_and_heuristics_are_not_crawl_domains,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} trading education corpus tests passed.")


if __name__ == "__main__":
    main()
