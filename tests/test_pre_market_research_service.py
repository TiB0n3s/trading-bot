import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pre_market_research_data import apply_event_enrichment
from repositories.pre_market_research_repo import PreMarketResearchRepository
from services.pre_market_research_service import (
    PreMarketResearchConfig,
    PreMarketResearchService,
)


def _bar(close, high=None, low=None):
    return SimpleNamespace(c=close, h=high if high is not None else close, l=low if low is not None else close)


def _pct_change(old, new):
    if old <= 0:
        return None
    return (new - old) / old * 100


def _unique_price_levels(levels, digits=2, limit=3):
    out = []
    seen = set()
    for level in levels:
        rounded = round(float(level), digits)
        if rounded <= 0 or rounded in seen:
            continue
        seen.add(rounded)
        out.append(rounded)
        if len(out) >= limit:
            break
    return out


class FakeMarketData:
    def __init__(self, daily_bars=None, minute_bars=None, daily_error=None):
        self.daily_bars = daily_bars or []
        self.minute_bars = minute_bars or []
        self.daily_error = daily_error
        self.calls = []

    def get_bars_with_fallback(self, symbol, timeframe, **kwargs):
        self.calls.append((symbol, timeframe, kwargs))
        if timeframe == "1Day":
            if self.daily_error:
                raise self.daily_error
            return self.daily_bars
        if timeframe == "1Min":
            return self.minute_bars
        raise AssertionError(f"unexpected timeframe {timeframe}")


class FakeRepository:
    def __init__(self):
        self.event_enrichment_payload = {"AAPL": {"catalyst_score": 42}}

    def event_enrichment(self, market_date):
        return self.event_enrichment_payload

    def latest_session_momentum(self, symbol):
        return {"symbol": symbol, "trend_label": "strong_uptrend"}

    def latest_prediction(self, symbol, market_date):
        return {"symbol": symbol, "market_date": market_date, "prediction_score": 61}

    def prior_session_context(self, symbol, market_date):
        return {"symbol": symbol, "market_date": market_date}

    def strategy_memory_context(self, symbol):
        return {"symbol": symbol, "trades": 3}


def _service(market_data, config=None, repository=None):
    return PreMarketResearchService(
        repository=repository or FakeRepository(),
        market_data=market_data,
        config=config
        or PreMarketResearchConfig(
            fetch_daily_bars=True,
            fetch_minute_bars=True,
            skip_minute_if_daily_fails=True,
            daily_lookback_days=7,
            minute_lookback_hours=3,
        ),
        pct_change=_pct_change,
        unique_price_levels=_unique_price_levels,
    )


def test_get_recent_bars_combines_daily_and_minute_context():
    minute_bars = [_bar(100 + i, high=101 + i, low=99 + i) for i in range(30)]
    service = _service(
        FakeMarketData(
            daily_bars=[_bar(95, high=98, low=94), _bar(100, high=102, low=96)],
            minute_bars=minute_bars,
        )
    )

    row = service.get_recent_bars("AAPL")

    assert row["symbol"] == "AAPL"
    assert round(row["daily_pct"], 3) == 5.263
    assert round(row["intraday_pct"], 3) == 29.0
    assert round(row["momentum_30m_pct"], 3) == 29.0
    assert row["last_price"] == 129.0
    assert row["bar_count_1m"] == 30
    assert row["support_levels"] == [99.0, 96.0, 94.0]
    assert row["resistance_levels"] == [130.0, 130.29]


def test_daily_failure_skips_minute_when_configured():
    service = _service(FakeMarketData(daily_error=RuntimeError("boom")))

    row = service.get_recent_bars("AAPL")

    assert "daily bars failed: boom" in row["error"]
    assert row["minute_fetch_skipped"] == "daily_failed"
    assert row["bar_count_1m"] == 0


def test_repository_reads_are_delegated():
    service = _service(FakeMarketData())

    assert service.load_event_enrichment("2026-05-30") == {"AAPL": {"catalyst_score": 42}}
    assert service.latest_session_momentum("AAPL")["trend_label"] == "strong_uptrend"
    assert service.get_latest_prediction("AAPL", "2026-05-30")["prediction_score"] == 61
    assert service.get_prior_session_context("AAPL", "2026-05-30")["symbol"] == "AAPL"
    assert service.get_strategy_memory_context("AAPL")["trades"] == 3


def test_repository_event_enrichment_includes_source_metadata(tmp_path):
    db_path = tmp_path / "trades.db"
    repo = PreMarketResearchRepository(db_path)
    repo.event_enrichment("2026-05-30")

    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO daily_symbol_context (
                market_date, symbol, catalyst_score, consumer_appetite_score,
                revenue_impact_score, profit_potential_score, margin_risk_score,
                supply_chain_risk_score, materials_risk_score, competitive_risk_score,
                execution_risk_score, created_at, updated_at
            ) VALUES (
                '2026-05-30', 'AAPL', 72, 65, 66, 67, 20, 21, 22, 23, 24,
                '2026-05-30T09:00:00', '2026-05-30T09:00:00'
            )
            """
        )
        con.executemany(
            """
            INSERT INTO daily_symbol_events (
                market_date, symbol, event_type, source, raw_json, created_at, updated_at
            ) VALUES ('2026-05-30', 'AAPL', 'guidance', ?, ?, '2026-05-30T09:00:00', '2026-05-30T09:00:00')
            """,
            [
                (
                    "reuters",
                    '{"intent_direction": "constructive", "intent_category": "company_fundamental_update", "intent_scope": "direct_company", "confirmation_status": "reputable_reported", "missing_evidence": []}',
                ),
                (
                    "morningstar",
                    '{"intent_direction": "constructive", "intent_category": "company_fundamental_update", "intent_scope": "direct_company", "confirmation_status": "reputable_reported", "missing_evidence": []}',
                ),
                (
                    "reuters",
                    '{"intent_direction": "constructive", "intent_category": "company_fundamental_update", "intent_scope": "direct_company", "confirmation_status": "reputable_reported", "missing_evidence": []}',
                ),
            ],
        )

    enrichment = repo.event_enrichment("2026-05-30")["AAPL"]

    assert enrichment["event_count"] == 3
    assert enrichment["source_count"] == 2
    assert set(enrichment["sources"]) == {"reuters", "morningstar"}
    assert enrichment["trusted_source_count"] == 2
    assert enrichment["confidence_cap"] == "two_independent_reputable_sources"
    assert enrichment["catalyst_score"] == 72
    assert enrichment["event_context"]["intent_directions"] == ["constructive"]
    assert enrichment["event_context"]["intent_categories"] == ["company_fundamental_update"]


def test_apply_event_enrichment_uses_multisource_confidence_text():
    entry = {"reason": "base", "key_risks": [], "key_catalysts": []}
    apply_event_enrichment(
        entry,
        {
            "catalyst_score": 72,
            "event_count": 3,
            "source_count": 2,
            "sources": ["reuters", "morningstar"],
            "source_tiers": ["confirmed_financial_news", "deep_analysis"],
            "trusted_source_count": 2,
            "confidence_cap": "two_independent_reputable_sources",
            "consumer_appetite_score": 70,
            "event_context": {
                "event_intent_version": "event_intent_aggregate_v1",
                "intent_directions": ["constructive"],
                "intent_categories": ["company_fundamental_update"],
                "intent_scopes": ["direct_company"],
                "confirmation_statuses": ["reputable_reported"],
                "missing_evidence": [],
            },
        },
    )

    context = entry["event_context"]
    assert context["source_count"] == 2
    assert context["sources"] == ["reuters", "morningstar"]
    assert context["trusted_source_count"] == 2
    assert context["confidence_cap"] == "two_independent_reputable_sources"
    assert context["intent_directions"] == ["constructive"]
    assert context["intent_categories"] == ["company_fundamental_update"]
    assert "confidence_cap=two_independent_reputable_sources" in entry["reason"]
    assert "intent=constructive" in entry["reason"]
    assert "trusted_sources=2" in entry["key_catalysts"][0]
    assert "event context is single-source headline-level only" not in entry["key_risks"]


if __name__ == "__main__":
    def _repo_metadata_test():
        with tempfile.TemporaryDirectory() as tmp:
            test_repository_event_enrichment_includes_source_metadata(Path(tmp))

    tests = [
        test_get_recent_bars_combines_daily_and_minute_context,
        test_daily_failure_skips_minute_when_configured,
        test_repository_reads_are_delegated,
        _repo_metadata_test,
        test_apply_event_enrichment_uses_multisource_confidence_text,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} pre-market research service tests passed.")
