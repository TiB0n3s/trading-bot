import sys
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.session_momentum_service import (
    SessionMomentumService,
    _session_start_or_lookback,
    _merge_retained_strength,
    classify_momentum_regime,
    classify_session_momentum,
)


def _bar(close, volume=10):
    return SimpleNamespace(c=close, h=close + 1, l=close - 1, v=volume)


class FakeMarketData:
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def get_bars_with_fallback(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.bars


class FakeRepository:
    def __init__(self, previous=None):
        self.previous = previous
        self.saved = None
        self.init_calls = 0

    def init_table(self):
        self.init_calls += 1

    def get_latest(self, symbol):
        return self.saved or self.previous

    def upsert(self, row):
        self.saved = dict(row)


def test_build_calculates_vwap_and_strong_uptrend():
    market_data = FakeMarketData([_bar(100), _bar(101), _bar(102), _bar(103), _bar(104)])
    service = SessionMomentumService(
        repository=FakeRepository(),
        market_data=market_data,
    )

    row = service.build("aapl")

    assert row["symbol"] == "AAPL"
    assert row["bar_count"] == 5
    assert row["session_open_price"] == 100
    assert row["latest_price"] == 104
    assert row["vwap"] == 102
    assert row["session_return_pct"] == 4
    assert row["distance_from_vwap_pct"] == 1.961
    assert row["trend_label"] == "strong_uptrend"
    assert row["trend_score"] == 8
    assert market_data.calls[0][0][:2] == ("AAPL", "1Min")
    assert market_data.calls[0][1]["feed"] == "iex"


def test_build_calculates_long_horizon_regime_fields():
    bars = [_bar(100 + i * 0.05) for i in range(130)]
    service = SessionMomentumService(
        repository=FakeRepository(),
        market_data=FakeMarketData(bars),
    )

    row = service.build("aapl")

    assert row["momentum_60m_pct"] is not None
    assert row["momentum_120m_pct"] is not None
    assert row["trend_regime"] in ("persistent_uptrend", "mature_uptrend")
    assert row["trend_persistence_score"] >= 4


def test_long_horizon_regime_detects_mature_chase():
    regime = classify_momentum_regime(
        session_return_pct=2.0,
        momentum_5m_pct=-0.1,
        momentum_15m_pct=0.2,
        momentum_30m_pct=0.7,
        momentum_60m_pct=1.2,
        momentum_120m_pct=1.8,
        distance_from_vwap_pct=1.7,
        pullback_from_session_high_pct=-0.02,
    )

    assert regime["late_chase_maturity_score"] >= 3
    assert regime["trend_regime"] in ("persistent_uptrend", "mature_uptrend")


def test_classification_labels_for_uptrend_fading_and_downtrend():
    uptrend = classify_session_momentum(
        session_return_pct=1.0,
        momentum_5m_pct=0.2,
        momentum_15m_pct=0.3,
        momentum_30m_pct=0.4,
        distance_from_vwap_pct=0.2,
        bar_count=5,
    )
    fading = classify_session_momentum(
        session_return_pct=-1.0,
        momentum_5m_pct=-0.2,
        momentum_15m_pct=0,
        momentum_30m_pct=0,
        distance_from_vwap_pct=-0.2,
        bar_count=5,
    )
    downtrend = classify_session_momentum(
        session_return_pct=-1.0,
        momentum_5m_pct=-0.2,
        momentum_15m_pct=-0.3,
        momentum_30m_pct=-0.4,
        distance_from_vwap_pct=-0.2,
        bar_count=5,
    )

    assert uptrend["trend_label"] == "strong_uptrend"
    assert fading["trend_label"] == "fading"
    assert downtrend["trend_label"] == "downtrend"


def test_session_start_anchors_to_market_open_after_open():
    start = _session_start_or_lookback(
        datetime(2026, 6, 1, 16, 0, tzinfo=timezone.utc),
        240,
    )

    assert start == datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc)


def test_refresh_symbol_upserts_merged_row():
    previous = {
        "symbol": "AAPL",
        "best_trend_score": 6,
        "best_session_return_pct": 3.0,
        "best_distance_from_vwap_pct": 2.0,
        "minutes_strong": 4,
        "strength_first_seen_at": "2026-05-30 10:00:00",
        "strength_last_seen_at": "2026-05-30 10:04:00",
        "session_strength_seen": 1,
    }
    repo = FakeRepository(previous=previous)
    service = SessionMomentumService(
        repository=repo,
        market_data=FakeMarketData([_bar(100), _bar(101), _bar(102), _bar(103), _bar(104)]),
    )

    row = service.refresh_symbol("AAPL")

    assert repo.init_calls == 1
    assert repo.saved is not None
    assert row["best_trend_score"] == 8
    assert row["best_session_return_pct"] == 4.0
    assert row["best_distance_from_vwap_pct"] == 2.0
    assert row["minutes_strong"] == 5
    assert row["strength_first_seen_at"] == "2026-05-30 10:00:00"
    assert row["session_strength_seen"] == 1


def test_missing_bars_returns_insufficient_data_safely():
    service = SessionMomentumService(
        repository=FakeRepository(),
        market_data=FakeMarketData([]),
    )

    row = service.build("AAPL")

    assert row["trend_label"] == "insufficient_data"
    assert row["trend_score"] == 0
    assert row["bar_count"] == 0
    assert row["latest_price"] is None


def test_retained_strength_preserves_prior_highs_and_tracks_pullback():
    previous = {
        "best_trend_score": 8,
        "best_session_return_pct": 3.0,
        "best_distance_from_vwap_pct": 1.5,
        "minutes_strong": 2,
        "strength_first_seen_at": "2026-05-30 10:00:00",
        "strength_last_seen_at": "2026-05-30 10:01:00",
        "session_strength_seen": 1,
    }
    row = {
        "updated_at": "2026-05-30 10:02:00",
        "trend_score": 7,
        "session_return_pct": 2.0,
        "distance_from_vwap_pct": 1.0,
    }

    merged = _merge_retained_strength(row, previous)

    assert merged["best_trend_score"] == 8
    assert merged["best_session_return_pct"] == 3.0
    assert merged["best_distance_from_vwap_pct"] == 1.5
    assert merged["minutes_strong"] == 3
    assert merged["strength_first_seen_at"] == "2026-05-30 10:00:00"
    assert merged["strength_last_seen_at"] == "2026-05-30 10:02:00"
    assert merged["pullback_from_session_high_pct"] == -1.0
    assert merged["session_strength_seen"] == 1


if __name__ == "__main__":
    tests = [
        test_build_calculates_vwap_and_strong_uptrend,
        test_build_calculates_long_horizon_regime_fields,
        test_long_horizon_regime_detects_mature_chase,
        test_classification_labels_for_uptrend_fading_and_downtrend,
        test_session_start_anchors_to_market_open_after_open,
        test_refresh_symbol_upserts_merged_row,
        test_missing_bars_returns_insufficient_data_safely,
        test_retained_strength_preserves_prior_highs_and_tracks_pullback,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} session momentum service tests passed.")
