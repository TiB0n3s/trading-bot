#!/usr/bin/env python3
"""Tests for curated trading education source policy."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.trading_education_corpus_service import (  # noqa: E402
    TRADING_EDUCATION_RUNTIME_EFFECT,
    TradingEducationIngestionService,
    approved_domains,
    build_trading_education_health_payload,
    classify_education_url,
)
from repositories.trading_education_repo import TradingEducationRepository  # noqa: E402


def test_trading_education_payload_is_non_authoritative_and_versioned():
    payload = build_trading_education_health_payload()

    assert payload["report_version"] == "trading_education_health_v1"
    assert payload["runtime_effect"] == TRADING_EDUCATION_RUNTIME_EFFECT
    assert payload["authority_ready"] is False
    assert payload["approved_seed_count"] >= 6
    assert payload["concept_count"] >= 10
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


def test_strategy_concepts_are_normalized_and_non_authoritative():
    payload = build_trading_education_health_payload()
    concepts = {concept["key"]: concept for concept in payload["concepts"]}

    expected = {
        "strategy_vs_style",
        "trend_trading",
        "range_trading",
        "breakout_trading",
        "reversal_trading",
        "gap_trading",
        "pairs_trading",
        "arbitrage",
        "momentum_trading",
        "risk_practice_before_live",
    }

    assert expected.issubset(concepts)
    assert concepts["breakout_trading"]["concept_type"] == "strategy_taxonomy"
    assert "volume_expansion" in concepts["breakout_trading"]["related_features"]
    assert "efi" in concepts["momentum_trading"]["related_features"]
    assert all(concept["live_authority"] == "education_context_only" for concept in concepts.values())


def test_education_ingestion_stores_compact_concept_metadata():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)

    def fake_transport(url: str) -> str:
        return """
        <html>
          <head><title>Breakout and Momentum Trading Basics</title></head>
          <body>
            <main>
              <p>A breakout strategy enters when price moves above resistance
              with volume expansion and continued momentum.</p>
              <p>Risk management and paper practice should be used before live trading.</p>
              <a href="/more-breakout-education">More</a>
              <a href="https://example.com/not-approved">Offsite</a>
            </main>
          </body>
        </html>
        """

    service = TradingEducationIngestionService(repo=repo, transport=fake_transport)
    result = service.ingest(max_pages=1, follow_links=True)
    summary = repo.summary()
    recent = repo.recent_pages(limit=1)

    assert result["runtime_effect"] == TRADING_EDUCATION_RUNTIME_EFFECT
    assert result["stored"] == 1
    assert summary["stored"] == 1
    assert recent[0]["status"] == "stored"
    assert "breakout_trading" in recent[0]["concept_keys"]
    assert "momentum_trading" in recent[0]["concept_keys"]
    assert "risk_practice_before_live" in recent[0]["concept_keys"]
    assert "volume_expansion" in recent[0]["related_features"]
    tmp.cleanup()


def test_education_ingestion_dry_run_does_not_persist():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(
        repo=repo,
        transport=lambda url: "<html><title>Trend</title><body>trend momentum risk</body></html>",
    )

    result = service.ingest(max_pages=1, dry_run=True)

    assert result["dry_run"] is True
    assert result["stored"] == 1
    assert repo.summary()["rows"] == 0
    tmp.cleanup()


def main():
    tests = [
        test_trading_education_payload_is_non_authoritative_and_versioned,
        test_classify_education_url_allows_only_curated_domains,
        test_books_and_heuristics_are_not_crawl_domains,
        test_strategy_concepts_are_normalized_and_non_authoritative,
        test_education_ingestion_stores_compact_concept_metadata,
        test_education_ingestion_dry_run_does_not_persist,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} trading education corpus tests passed.")


if __name__ == "__main__":
    main()
