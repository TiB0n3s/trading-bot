import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.live_features_service import LiveFeaturesService  # noqa: E402


class FakeRepository:
    def __init__(self):
        self.inserted = None
        self.latest = None

    def recent_actions(self, symbol, limit=10):
        return ["buy", "buy", "buy", "sell"][:limit]

    def insert_snapshot(self, snapshot):
        self.inserted = dict(snapshot)

    def latest_snapshot(self, symbol):
        return dict(self.latest) if self.latest else None


class FakeMarketData:
    def __init__(self, rows, fail_symbols=None):
        self.rows = rows
        self.calls = []
        self.fail_symbols = set(fail_symbols or ())

    def get_barset_with_fallback(self, symbol, timeframe, **kwargs):
        self.calls.append((symbol, timeframe, kwargs))
        if symbol in self.fail_symbols:
            return SimpleNamespace(df=pd.DataFrame())
        df = pd.DataFrame(self.rows)
        if self.calls[-1][0] == "SPY":
            df = df.assign(symbol="SPY")
        return SimpleNamespace(df=df)

    def get_feed_used(self, symbol):
        return "iex"


def _setup_classifier(snapshot):
    return SimpleNamespace(
        setup_label="confirmed_near_vwap_recovery",
        recommendation="boost",
        setup_score=72,
        confidence="medium",
        setup_key="test-key",
        rationale="test rationale",
    )


def _feature_snapshot_builder(**kwargs):
    closes = kwargs["closes"]
    return {
        "symbol": kwargs["symbol"],
        "benchmark_symbol": kwargs["benchmark_symbol"],
        "last_price": closes[-1],
        "ret_1m": 0.1,
        "ret_5m": 0.5,
        "ret_15m": 1.5,
        "market_session": kwargs["market_session"],
        "macro_regime": kwargs["macro_regime"],
        "market_bias": kwargs["market_bias"],
        "trend_direction": kwargs["trend_direction"],
        "trend_strength": kwargs["trend_strength"],
    }


def _service(tmp_path):
    (tmp_path / "market_context.json").write_text('{"symbols": {"AAPL": {"bias": "buy"}}}')
    rows = [{"symbol": "AAPL", "close": 100 + i, "volume": 1000 + i} for i in range(20)]
    repo = FakeRepository()
    service = LiveFeaturesService(
        repository=repo,
        market_data=FakeMarketData(rows),
        base_dir=tmp_path,
        approved_symbols={"AAPL", "SPY"},
        symbol_market_alignment={"AAPL": {"benchmark": "SPY"}},
        macro_risk_provider=lambda base_dir: {"macro_regime": "risk_on"},
        market_session_provider=lambda: "open",
        feature_snapshot_builder=_feature_snapshot_builder,
        setup_classifier=_setup_classifier,
        rolling_context_provider=lambda symbol: {"extension_from_recent_base_pct": 1.25},
        prior_session_provider=lambda symbol: {"session_return_pct": 2.5},
    )
    return service, repo


def test_build_snapshot_uses_market_data_repository_context_and_setup(tmp_path):
    service, _repo = _service(tmp_path)

    snapshot = service.build_snapshot("aapl")

    assert snapshot["symbol"] == "AAPL"
    assert snapshot["benchmark_symbol"] == "SPY"
    assert snapshot["bar_timeframe"] == "1Min"
    assert snapshot["bar_count"] == 20
    assert snapshot["bar_feed_used"] == "iex"
    assert snapshot["macro_regime"] == "risk_on"
    assert snapshot["market_bias"] == "buy"
    assert snapshot["trend_direction"] == "bullish"
    assert snapshot["trend_strength"] == "developing"
    assert snapshot["momentum_acceleration_pct"] is not None
    assert snapshot["volume_surge_ratio"] is not None
    assert snapshot["extension_from_recent_base_pct"] == 1.25
    assert snapshot["prior_session_return_pct"] == 2.5
    assert snapshot["setup_label"] == "confirmed_near_vwap_recovery"
    assert snapshot["feature_available_at"]


def test_insert_snapshot_delegates_to_repository(tmp_path):
    service, repo = _service(tmp_path)

    service.insert_snapshot({"symbol": "AAPL", "last_price": 123})

    assert repo.inserted == {"symbol": "AAPL", "last_price": 123}


def test_collect_all_symbols_reuses_latest_snapshot_as_stale_when_feed_is_thin(tmp_path):
    service, repo = _service(tmp_path)
    repo.latest = {
        "symbol": "AAPL",
        "timestamp": "2026-06-09T09:45:00-04:00",
        "last_price": 101.0,
        "ret_5m": 0.2,
        "source": "live_features",
        "is_stale": 0,
        "staleness_reason": None,
    }
    service.market_data = FakeMarketData(
        [{"symbol": "SPY", "close": 100 + i, "volume": 1000 + i} for i in range(20)],
        fail_symbols={"AAPL"},
    )
    service.approved_symbols = {"AAPL"}

    success, failed = service.collect_all_symbols(write=True)

    assert success == 1
    assert failed == 0
    assert repo.inserted["symbol"] == "AAPL"
    assert repo.inserted["last_price"] == 101.0
    assert repo.inserted["is_stale"] == 1
    assert repo.inserted["source"] == "live_features_degraded_fallback"
    assert repo.inserted["previous_snapshot_timestamp"] == "2026-06-09T09:45:00-04:00"
    assert repo.inserted["staleness_reason"].startswith("thin_feed_reused_previous_snapshot:")


if __name__ == "__main__":
    tests = [
        test_build_snapshot_uses_market_data_repository_context_and_setup,
        test_insert_snapshot_delegates_to_repository,
        test_collect_all_symbols_reuses_latest_snapshot_as_stale_when_feed_is_thin,
    ]
    import tempfile

    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} live features service tests passed.")
