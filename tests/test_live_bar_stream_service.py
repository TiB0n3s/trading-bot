import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.live_bar_stream_service import (  # noqa: E402
    LIVE_BAR_RUNTIME_EFFECT,
    LiveBarStreamService,
    normalize_live_bar,
)


def _bar(symbol="AAPL", close=100.0, minute=0):
    ts = datetime(2026, 6, 4, 13, 30, tzinfo=timezone.utc) + timedelta(minutes=minute)
    return SimpleNamespace(
        symbol=symbol,
        timestamp=ts,
        open=close - 0.1,
        high=close + 0.2,
        low=close - 0.2,
        close=close,
        volume=1000 + minute,
        vwap=close - 0.03,
    )


class FakeSessionMomentum:
    def __init__(self):
        self.calls = []

    def refresh_from_bars(self, symbol, bars):
        self.calls.append((symbol, list(bars)))
        latest = bars[-1]
        return {
            "symbol": symbol,
            "trend_label": "developing_uptrend" if len(bars) >= 5 else "insufficient_data",
            "trend_score": 4 if len(bars) >= 5 else 0,
            "latest_price": latest["close"],
        }


class FakeMarketData:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_recent_bar_dicts(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return list(self.rows)


class FakeStream:
    instances = []

    def __init__(self, api_key, secret_key, feed):
        self.api_key = api_key
        self.secret_key = secret_key
        self.feed = feed
        self.subscriptions = []
        self.ran = False
        FakeStream.instances.append(self)

    def subscribe_bars(self, handler, *symbols):
        self.subscriptions.append((handler, symbols))

    def run(self):
        self.ran = True


def test_normalize_live_bar_maps_alpaca_py_shape():
    normalized = normalize_live_bar(_bar(close=101.5), feed="iex")

    assert normalized["symbol"] == "AAPL"
    assert normalized["open"] == 101.4
    assert normalized["high"] == 101.7
    assert normalized["low"] == 101.3
    assert normalized["close"] == 101.5
    assert normalized["volume"] == 1000
    assert normalized["vwap"] == 101.47
    assert normalized["timestamp"].endswith("+00:00")
    assert normalized["source"] == "alpaca_live_bar_stream"
    assert normalized["feed"] == "iex"
    assert normalized["interval_semantics"] == "inclusive_start_live_closed_1m"


def test_ingest_bar_gap_fills_then_updates_session_momentum():
    fill_rows = [
        {
            "symbol": "AAPL",
            "timestamp": (
                datetime(2026, 6, 4, 13, 30, tzinfo=timezone.utc) + timedelta(minutes=i)
            ).isoformat(),
            "open": 100 + i,
            "high": 100.2 + i,
            "low": 99.8 + i,
            "close": 100 + i,
            "volume": 1000 + i,
        }
        for i in range(4)
    ]
    session = FakeSessionMomentum()
    market_data = FakeMarketData(fill_rows)
    service = LiveBarStreamService(
        session_momentum_service=session,
        market_data=market_data,
        api_key="key",
        secret_key="secret",
        feed="iex",
    )

    result = service.ingest_bar(_bar(close=104, minute=4))

    assert result.runtime_effect == LIVE_BAR_RUNTIME_EFFECT
    assert result.symbol == "AAPL"
    assert result.feed == "iex"
    assert result.gap_fill_attempted is True
    assert result.gap_fill_rows == 4
    assert result.rolling_bars == 5
    assert result.trend_label == "developing_uptrend"
    assert market_data.calls[0][0] == "AAPL"
    assert market_data.calls[0][1]["feed"] == "iex"
    assert len(session.calls) == 1
    assert len(session.calls[0][1]) == 5
    assert session.calls[0][1][0]["source"] == "alpaca_gap_fill_bars"
    assert session.calls[0][1][0]["feed"] == "iex"
    assert session.calls[0][1][-1]["source"] == "alpaca_live_bar_stream"
    assert session.calls[0][1][-1]["interval_semantics"] == "inclusive_start_live_closed_1m"


def test_ingest_bar_gap_fills_again_after_stream_gap():
    session = FakeSessionMomentum()
    market_data = FakeMarketData([])
    service = LiveBarStreamService(
        session_momentum_service=session,
        market_data=market_data,
        api_key="key",
        secret_key="secret",
    )

    first = service.ingest_bar(_bar(minute=1))
    second = service.ingest_bar(_bar(minute=5))

    assert first.gap_fill_attempted is True
    assert second.gap_fill_attempted is True
    assert len(market_data.calls) == 2
    assert second.rolling_bars == 2


def test_single_minute_drop_flags_discontinuity_and_gap_fills():
    # One missing bar (minute 2) produces a 2-minute gap, which the old
    # ">2 minutes" threshold silently skipped. It must now be flagged. (#21)
    session = FakeSessionMomentum()
    market_data = FakeMarketData([])
    service = LiveBarStreamService(
        session_momentum_service=session,
        market_data=market_data,
        api_key="key",
        secret_key="secret",
    )

    service.ingest_bar(_bar(minute=1))  # 13:31
    result = service.ingest_bar(_bar(minute=3))  # 13:33 -> 2 min gap (minute 2 missing)

    assert result.discontinuity_minutes == 2.0
    assert result.gap_fill_attempted is True


def test_consecutive_bars_have_no_discontinuity():
    session = FakeSessionMomentum()
    market_data = FakeMarketData([])
    service = LiveBarStreamService(
        session_momentum_service=session,
        market_data=market_data,
        api_key="key",
        secret_key="secret",
    )

    service.ingest_bar(_bar(minute=1))
    result = service.ingest_bar(_bar(minute=2))  # normal 1-minute cadence

    assert result.discontinuity_minutes is None


def test_run_stream_once_subscribes_symbols_with_injected_stream():
    FakeStream.instances = []
    service = LiveBarStreamService(
        session_momentum_service=FakeSessionMomentum(),
        market_data=FakeMarketData([]),
        stream_cls=FakeStream,
        api_key="key",
        secret_key="secret",
        feed="iex",
    )

    service.run_stream_once(["aapl", "msft"])

    stream = FakeStream.instances[0]
    assert stream.feed == "iex"
    assert stream.ran is True
    assert stream.subscriptions
    assert stream.subscriptions[0][1] == ("AAPL", "MSFT")


def test_missing_credentials_raise_before_stream_creation():
    service = LiveBarStreamService(
        session_momentum_service=FakeSessionMomentum(),
        market_data=FakeMarketData([]),
        stream_cls=FakeStream,
        api_key="",
        secret_key="",
    )

    try:
        service.run_stream_once(["AAPL"])
    except RuntimeError as exc:
        assert "ALPACA_API_KEY" in str(exc)
    else:
        raise AssertionError("expected missing credential error")


def main():
    tests = [
        test_normalize_live_bar_maps_alpaca_py_shape,
        test_ingest_bar_gap_fills_then_updates_session_momentum,
        test_ingest_bar_gap_fills_again_after_stream_gap,
        test_run_stream_once_subscribes_symbols_with_injected_stream,
        test_missing_credentials_raise_before_stream_creation,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} live bar stream service tests passed.")


if __name__ == "__main__":
    main()
