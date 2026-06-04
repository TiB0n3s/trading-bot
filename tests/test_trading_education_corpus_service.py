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
    assert "schwab.com" in payload["approved_domains"]


def test_classify_education_url_allows_only_curated_domains():
    sec = classify_education_url("https://www.investor.gov/introduction-investing")
    investopedia = classify_education_url("https://www.investopedia.com/terms/v/vwap.asp")
    schwab = classify_education_url("https://www.schwab.com/learn/trading")
    unknown = classify_education_url("https://example.com/trading-course")

    assert sec["matched"] is True
    assert sec["tier"] == "official_highest"
    assert sec["link_follow_policy"] == "same_domain_only"
    assert investopedia["matched"] is True
    assert investopedia["ingestion_status"] == "approved_context_seed"
    assert schwab["matched"] is True
    assert schwab["source_type"] == "broker_education"
    assert schwab["authority"] == "education_context_only"
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
        "backtesting_overfitting_control",
    }

    assert expected.issubset(concepts)
    assert concepts["breakout_trading"]["concept_type"] == "strategy_taxonomy"
    assert "volume_expansion" in concepts["breakout_trading"]["related_features"]
    assert "efi" in concepts["momentum_trading"]["related_features"]
    assert "walk_forward_window" in concepts["backtesting_overfitting_control"]["related_features"]
    assert "out-of-sample" in concepts["backtesting_overfitting_control"]["summary"]
    assert all(concept["live_authority"] == "education_context_only" for concept in concepts.values())


def test_education_ingestion_stores_compact_concept_metadata():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)

    def fake_transport(url: str) -> str:
        return """
        <html>
          <head><title>Breakout, Momentum, and Backtesting Basics</title></head>
          <body>
            <main>
              <p>A breakout strategy enters when price moves above resistance
              with volume expansion and continued momentum.</p>
              <p>Risk management and paper practice should be used before live trading.</p>
              <p>Backtesting should use out-of-sample data and walk-forward validation
              to reduce overfitting risk and evaluate drawdowns.</p>
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
    assert "backtesting_overfitting_control" in recent[0]["concept_keys"]
    assert "volume_expansion" in recent[0]["related_features"]
    assert "overfit_risk" in recent[0]["related_features"]
    tmp.cleanup()


def test_schwab_child_seeds_are_approved_and_blocked_pages_fail(tmp_path=None):
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(
        repo=repo,
        transport=lambda url: (
            "<html><head><title>Charles Schwab</title></head><body>"
            "We’re sorry, but we were unable to authorize your request."
            "</body></html>"
            if "schwab.com" in url
            else "<html><title>Options Strategy</title><body>covered call strategy risks options liquidity</body></html>"
        ),
    )

    schwab_pairs = [
        url
        for source, url in service.approved_seed_pairs()
        if source.key == "schwab_learn_trading"
    ]
    assert "https://www.schwab.com/learn/story/what-are-derivatives" in schwab_pairs
    assert "https://www.schwab.com/learn/story/options-strategy-covered-call" in schwab_pairs

    result = service.ingest(max_pages=len(service.approved_seed_pairs()), follow_links=False)
    summary = repo.summary()

    assert result["failed"] >= len(schwab_pairs)
    assert summary["by_source"]
    assert any(
        row["source_key"] == "schwab_learn_trading" and row["status"] == "fetch_failed"
        for row in summary["by_source"]
    )
    assert not any(
        row["source_key"] == "schwab_learn_trading"
        for row in repo.recent_pages(limit=20, stored_only=True)
    )
    tmp.cleanup()


def test_manual_snapshot_ingest_accepts_uploaded_schwab_card_content():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)

    result = service.ingest_manual_snapshot(
        url="https://www.schwab.com/learn/story/what-are-derivatives",
        title="What Are Derivatives? A Guide to Financial Contracts",
        content=(
            "Derivatives are financial contracts whose value comes from an underlying asset. "
            "Options, futures, swaps, and forwards may be used in trading strategies to manage risk, "
            "generate income, or speculate on price changes. Derivatives involve significant risks, including "
            "leverage, liquidity, expiration, assignment, and amplified losses."
        ),
    )
    recent = repo.recent_pages(limit=1)

    assert result["status"] in {"stored", "needs_review"}
    assert result["corpus_version"] == "trading_education_corpus_v1"
    assert result["runtime_effect"] == TRADING_EDUCATION_RUNTIME_EFFECT
    assert result["source_key"] == "schwab_learn_trading"
    assert "risk_practice_before_live" in result["concept_keys"]
    assert "strategy_vs_style" in result["concept_keys"]
    assert recent[0]["ingestion_method"] == "manual_snapshot"
    assert recent[0]["extraction_confidence"] is not None
    tmp.cleanup()


def test_manual_snapshot_blocks_unapproved_urls():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)

    result = service.ingest_manual_snapshot(
        url="https://example.com/not-approved",
        title="Not Approved",
        content="options risk strategy",
    )

    assert result["status"] == "blocked"
    assert repo.summary()["rows"] == 0
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
    assert result["stored"] + result["needs_review"] == 1
    assert repo.summary()["rows"] == 0
    tmp.cleanup()


def main():
    tests = [
        test_trading_education_payload_is_non_authoritative_and_versioned,
        test_classify_education_url_allows_only_curated_domains,
        test_books_and_heuristics_are_not_crawl_domains,
        test_strategy_concepts_are_normalized_and_non_authoritative,
        test_education_ingestion_stores_compact_concept_metadata,
        test_schwab_child_seeds_are_approved_and_blocked_pages_fail,
        test_manual_snapshot_ingest_accepts_uploaded_schwab_card_content,
        test_manual_snapshot_blocks_unapproved_urls,
        test_education_ingestion_dry_run_does_not_persist,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} trading education corpus tests passed.")


if __name__ == "__main__":
    main()
