#!/usr/bin/env python3
"""Tests for curated trading education source policy."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.trading_education_repo import TradingEducationRepository  # noqa: E402
from services.intelligence.education.corpus import (  # noqa: E402
    TRADING_EDUCATION_RUNTIME_EFFECT,
    TradingEducationIngestionService,
    approved_domains,
    build_trading_education_health_payload,
    classify_education_url,
)
from services.intelligence.education.coverage import (  # noqa: E402
    build_trading_education_coverage_payload,
)
from services.intelligence.education.decision_context import (  # noqa: E402
    EDUCATION_DECISION_RUNTIME_EFFECT,
    education_context_for_account_state,
)


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
        "news_expectations_positioning",
        "short_selling_risk",
        "rally_exhaustion_exit_patterns",
        "implied_volatility_context",
        "heikin_ashi_trend_reversal",
        "ipo_liquidity_restrictions",
        "algorithmic_trading_pipeline",
    }

    assert expected.issubset(concepts)
    assert concepts["breakout_trading"]["concept_type"] == "strategy_taxonomy"
    assert "volume_expansion" in concepts["breakout_trading"]["related_features"]
    assert "efi" in concepts["momentum_trading"]["related_features"]
    assert "walk_forward_window" in concepts["backtesting_overfitting_control"]["related_features"]
    assert "priced_in_risk" in concepts["news_expectations_positioning"]["related_features"]
    assert "short_squeeze_risk" in concepts["short_selling_risk"]["related_features"]
    assert "bearish_engulfing" in concepts["rally_exhaustion_exit_patterns"]["related_features"]
    assert "expected_move" in concepts["implied_volatility_context"]["related_features"]
    assert "heikin_ashi_color_run" in concepts["heikin_ashi_trend_reversal"]["related_features"]
    assert "lockup_expiration" in concepts["ipo_liquidity_restrictions"]["related_features"]
    assert "data_leakage_guard" in concepts["algorithmic_trading_pipeline"]["related_features"]
    assert "paper_trading_duration" in concepts["algorithmic_trading_pipeline"]["related_features"]
    assert "pandas_numpy_stack" in concepts["algorithmic_trading_pipeline"]["related_features"]
    assert (
        "stationary_return_transform"
        in concepts["algorithmic_trading_pipeline"]["related_features"]
    )
    assert "time_series_split" in concepts["algorithmic_trading_pipeline"]["related_features"]
    assert "out-of-sample" in concepts["backtesting_overfitting_control"]["summary"]
    assert all(
        concept["live_authority"] == "education_context_only" for concept in concepts.values()
    )


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
        url for source, url in service.approved_seed_pairs() if source.key == "schwab_learn_trading"
    ]
    assert "https://www.schwab.com/learn/story/what-are-derivatives" in schwab_pairs
    assert "https://www.schwab.com/learn/story/options-strategy-covered-call" in schwab_pairs
    assert (
        "https://www.schwab.com/learn/story/why-stocks-sometimes-ignore-good-or-bad-news"
        in schwab_pairs
    )
    assert "https://www.schwab.com/learn/story/ins-and-outs-short-selling" in schwab_pairs
    assert (
        "https://www.schwab.com/learn/story/ways-traders-spot-rallys-potential-end" in schwab_pairs
    )
    assert (
        "https://www.schwab.com/learn/story/aligning-your-options-with-implied-volatility"
        in schwab_pairs
    )
    assert (
        "https://www.schwab.com/learn/story/heikin-ashi-candles-reversals-and-strategies"
        in schwab_pairs
    )
    assert (
        "https://www.schwab.com/learn/story/pre-ipo-company-equity-6-actions-to-take-now"
        in schwab_pairs
    )

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


def test_manual_snapshot_maps_expectations_and_positioning_article():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)

    result = service.ingest_manual_snapshot(
        url="https://www.schwab.com/learn/story/why-stocks-sometimes-ignore-good-or-bad-news",
        title="Why Stocks Sometimes Ignore Good (or Bad) News",
        content=(
            "Stocks may ignore good news when expectations were already priced in. "
            "Investors can buy the rumor and sell the news after an earnings call, "
            "especially when forward guidance disappoints. Market sentiment, positioning, "
            "institutional flows, index changes, tax-loss harvesting, and margin calls can "
            "also dominate a headline."
        ),
    )

    assert result["status"] in {"stored", "needs_review"}
    assert "news_expectations_positioning" in result["concept_keys"]
    assert "priced_in_risk" in result["related_features"]
    tmp.cleanup()


def test_manual_snapshot_maps_short_selling_risk_article():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)

    result = service.ingest_manual_snapshot(
        url="https://www.schwab.com/learn/story/ins-and-outs-short-selling",
        title="Short Selling: The Risks and Rewards",
        content=(
            "Short selling involves borrowing shares and selling them, then buying them "
            "back later. Short sellers face borrow availability, locate requirements, "
            "short squeeze risk, margin calls, dividend payments, buy-stop orders, "
            "and potentially limitless losses."
        ),
    )

    assert result["status"] in {"stored", "needs_review"}
    assert "short_selling_risk" in result["concept_keys"]
    assert "short_squeeze_risk" in result["related_features"]
    tmp.cleanup()


def test_manual_snapshot_maps_rally_exhaustion_exit_article():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)

    result = service.ingest_manual_snapshot(
        url="https://www.schwab.com/learn/story/ways-traders-spot-rallys-potential-end",
        title="4 Ways Traders Spot a Rally's Potential End",
        content=(
            "A rally may be coming to an end when good news is bad news, dip buyers stop "
            "getting rewarded, a sharp top becomes parabolic, or a stock closes near the "
            "day's lows. Bearish engulfing, dark cloud cover, shooting star, three black "
            "crows, advance block, and negative divergence can corroborate exit review."
        ),
    )

    assert result["status"] in {"stored", "needs_review"}
    assert "rally_exhaustion_exit_patterns" in result["concept_keys"]
    assert "bearish_engulfing" in result["related_features"]
    tmp.cleanup()


def test_manual_snapshot_maps_implied_volatility_article():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)

    result = service.ingest_manual_snapshot(
        url="https://www.schwab.com/learn/story/aligning-your-options-with-implied-volatility",
        title="Aligning Options Strategies and Implied Volatility",
        content=(
            "Implied volatility estimates expected volatility and expected move magnitude, "
            "not direction. Traders compare historical volatility, IV rank, IV percentile, "
            "probability cones, VIX, short vega, long vega, term structure, and tail risk."
        ),
    )

    assert result["status"] in {"stored", "needs_review"}
    assert "implied_volatility_context" in result["concept_keys"]
    assert "expected_move" in result["related_features"]
    tmp.cleanup()


def test_manual_snapshot_maps_heikin_ashi_article():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)

    result = service.ingest_manual_snapshot(
        url="https://www.schwab.com/learn/story/heikin-ashi-candles-reversals-and-strategies",
        title="How to Use Heikin Ashi Charts",
        content=(
            "Heikin ashi average bar charts smooth price action. A heikin ashi bar run, "
            "short-range bars, bars without bottom wicks, and an eight-period EMA crossing "
            "a 21-period EMA may help identify trend reversals."
        ),
    )

    assert result["status"] in {"stored", "needs_review"}
    assert "heikin_ashi_trend_reversal" in result["concept_keys"]
    assert "heikin_ashi_color_run" in result["related_features"]
    tmp.cleanup()


def test_manual_snapshot_maps_ipo_liquidity_restrictions_article():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)

    result = service.ingest_manual_snapshot(
        url="https://www.schwab.com/learn/story/pre-ipo-company-equity-6-actions-to-take-now",
        title="Pre-IPO Company Equity: 6 Actions to Take Now",
        content=(
            "Pre-IPO employees should review the S-1, equity incentive plan, award agreement, "
            "tender offer terms, lock-up period, blackout period, trading window, 10b5-1 plan, "
            "dilution, and concentration risk before liquidity events."
        ),
    )

    assert result["status"] in {"stored", "needs_review"}
    assert "ipo_liquidity_restrictions" in result["concept_keys"]
    assert "lockup_expiration" in result["related_features"]
    tmp.cleanup()


def test_manual_snapshot_maps_algorithmic_trading_pipeline_guidance():
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)

    result = service.ingest_manual_snapshot(
        url="https://www.schwab.com/learn/trading",
        title="Operator note: algorithmic trading pipeline",
        content=(
            "To build an algorithmic system to read and predict market trends, define asset "
            "classes, establish timeframes, formulate hypotheses, ingest OHLCV and alternative "
            "data, calculate technical indicators such as moving averages, relative strength "
            "index, and Bollinger Bands, choose predictive model architecture such as ARIMA, "
            "GARCH, XGBoost, LSTM, Transformers, or FinBERT, build a backtesting engine that "
            "avoids data leakage and includes transactional variables, Sharpe Ratio, Maximum "
            "Drawdown, Win/Loss Ratio, position sizing, Kelly Criterion, portfolio "
            "diversification, paper trading, and system latency checks. Practical Python tools "
            "include pandas, numpy, yfinance, Alpaca, Interactive Brokers, TA-Lib, "
            "scikit-learn, RandomForest, logistic regression, Backtrader, and vectorbt. "
            "Use train_test_split with shuffle=False, avoid look-ahead bias, and convert "
            "raw prices into stationary data such as log returns or percentage changes."
        ),
    )

    assert result["status"] in {"stored", "needs_review"}
    assert result["runtime_effect"] == TRADING_EDUCATION_RUNTIME_EFFECT
    assert "algorithmic_trading_pipeline" in result["concept_keys"]
    assert "data_leakage_guard" in result["related_features"]
    assert "stationary_return_transform" in result["related_features"]
    assert "time_series_split" in result["related_features"]
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


def test_trading_education_coverage_reports_storage_gaps_and_readiness():
    tmp = tempfile.TemporaryDirectory()
    base_dir = Path(tmp.name)
    db_path = base_dir / "trades.db"
    repo = TradingEducationRepository(db_path)
    service = TradingEducationIngestionService(repo=repo)
    service.ingest_manual_snapshot(
        url="https://www.schwab.com/learn/story/ways-traders-spot-rallys-potential-end",
        title="4 Ways Traders Spot a Rally's Potential End",
        content=(
            "A rally may be coming to an end when good news is bad news, dip buyers stop "
            "getting rewarded, price turns parabolic, and a stock closes near the day's lows. "
            "Bearish engulfing candles, dark cloud cover, shooting stars, three black crows, "
            "advance block, and negative divergence can corroborate momentum deterioration. "
            "These reversal patterns should be treated as yellow flags for exit review and "
            "winner-became-loser diagnostics, not standalone sell authority."
        ),
    )
    (base_dir / "local_feature.py").write_text(
        "exit_decision_quality winner-became-loser point_in_time_archive "
        "candidate_outcome slippage shadow_prediction rollout_contract "
        "bearish_engulfing close_near_low down_volume_pressure"
    )

    payload = build_trading_education_coverage_payload(base_dir=base_dir, repo=repo)
    rows = {row["key"]: row for row in payload["concepts"]}

    assert payload["report_version"] == "trading_education_coverage_v1"
    assert payload["runtime_effect"] == TRADING_EDUCATION_RUNTIME_EFFECT
    assert rows["rally_exhaustion_exit_patterns"]["stored_pages"] == 1
    assert rows["rally_exhaustion_exit_patterns"]["coverage_status"] == "connected"
    assert all(row["present"] for row in payload["backtest_readiness"])
    assert (
        "live approval/sizing/execution requires explicit promotion"
        in payload["decision_influence_policy"]
    )
    tmp.cleanup()


def test_education_context_can_inform_decision_context_without_authority():
    payload = education_context_for_account_state(
        {
            "action": "buy",
            "event_context": {
                "event_signal": "headline_watch",
                "summary": "earnings guidance headline may already be priced in",
            },
            "prediction_gate": {"prediction_score": 62, "prediction_decision": "allow"},
            "market_microstructure": {"breakout_quality": "confirmed_breakout"},
            "momentum": {"direction": "rising", "state": "accelerating"},
        }
    )
    keys = {row["key"] for row in payload["concepts"]}

    assert payload["runtime_effect"] == EDUCATION_DECISION_RUNTIME_EFFECT
    assert "news_expectations_positioning" in keys
    assert "breakout_trading" in keys
    assert "algorithmic_trading_pipeline" in keys
    assert "cannot directly" in payload["authority_note"]
    assert all("execute" not in row["influence_policy"].lower() for row in payload["concepts"])


def test_runtime_education_context_does_not_import_education_repository_or_table():
    runtime_files = [
        ROOT / "scripts" / "decision_context.py",
        ROOT / "src" / "trading_bot" / "signals" / "context" / "builder.py",
        ROOT
        / "src"
        / "trading_bot"
        / "services"
        / "intelligence"
        / "education"
        / "decision_context.py",
    ]
    combined = "\n".join(path.read_text() for path in runtime_files)

    assert "TradingEducationRepository" not in combined
    assert "trading_education_pages" not in combined
    assert ".upsert_page(" not in combined


def main():
    tests = [
        test_trading_education_payload_is_non_authoritative_and_versioned,
        test_classify_education_url_allows_only_curated_domains,
        test_books_and_heuristics_are_not_crawl_domains,
        test_strategy_concepts_are_normalized_and_non_authoritative,
        test_education_ingestion_stores_compact_concept_metadata,
        test_schwab_child_seeds_are_approved_and_blocked_pages_fail,
        test_manual_snapshot_ingest_accepts_uploaded_schwab_card_content,
        test_manual_snapshot_maps_expectations_and_positioning_article,
        test_manual_snapshot_maps_short_selling_risk_article,
        test_manual_snapshot_maps_rally_exhaustion_exit_article,
        test_manual_snapshot_maps_implied_volatility_article,
        test_manual_snapshot_maps_heikin_ashi_article,
        test_manual_snapshot_maps_ipo_liquidity_restrictions_article,
        test_manual_snapshot_maps_algorithmic_trading_pipeline_guidance,
        test_manual_snapshot_blocks_unapproved_urls,
        test_education_ingestion_dry_run_does_not_persist,
        test_trading_education_coverage_reports_storage_gaps_and_readiness,
        test_education_context_can_inform_decision_context_without_authority,
        test_runtime_education_context_does_not_import_education_repository_or_table,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} trading education corpus tests passed.")


if __name__ == "__main__":
    main()
