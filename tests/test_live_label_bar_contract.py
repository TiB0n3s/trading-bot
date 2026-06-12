import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.canonical_bar_contract import (  # noqa: E402
    CANONICAL_BAR_REQUIRED_FIELDS,
    CANONICAL_BAR_TIMEFRAME,
    dataframe_to_canonical_bar_rows,
)
from services.label_features_market_data_service import LabelFeaturesMarketDataService  # noqa: E402

import scripts.label_features as label_features_script  # noqa: E402
import scripts.live_features as live_features_script  # noqa: E402


class FakeMarketData:
    def __init__(self):
        self.calls = []
        index = pd.date_range("2026-06-10T09:30:00-04:00", periods=3, freq="min")
        self.df = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.5,
                    "close": 100.5,
                    "volume": 1000,
                    "vwap": 100.25,
                },
                {
                    "symbol": "AAPL",
                    "open": 100.5,
                    "high": 102.0,
                    "low": 100.0,
                    "close": 101.5,
                    "volume": 1200,
                    "vwap": 101.2,
                },
                {
                    "symbol": "MSFT",
                    "open": 200.0,
                    "high": 201.0,
                    "low": 199.5,
                    "close": 200.5,
                    "volume": 2000,
                    "vwap": 200.2,
                },
            ],
            index=index,
        )

    def get_barset_with_fallback(self, symbol, timeframe, **kwargs):
        self.calls.append((symbol, timeframe, kwargs))
        return SimpleNamespace(df=self.df)

    def get_feed_used(self, symbol):
        return "iex"


class FakeListMarketData:
    def __init__(self):
        self.calls = []
        self.rows = [
            {
                "symbol": "AAPL",
                "timestamp": pd.Timestamp("2026-06-10T09:30:00-04:00"),
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
                "volume": 1000,
                "vwap": 100.25,
            },
            {
                "symbol": "MSFT",
                "timestamp": pd.Timestamp("2026-06-10T09:30:00-04:00"),
                "open": 200.0,
                "high": 201.0,
                "low": 199.5,
                "close": 200.5,
                "volume": 2000,
                "vwap": 200.2,
            },
        ]

    def get_barset_with_fallback(self, symbol, timeframe, **kwargs):
        self.calls.append((symbol, timeframe, kwargs))
        return list(self.rows)

    def get_feed_used(self, symbol):
        return "iex"


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def test_label_features_script_uses_repo_root_like_live_features():
    assert_equal(label_features_script.BASE_DIR, live_features_script.BASE_DIR, "base dir")
    assert_equal(label_features_script.BASE_DIR, ROOT, "repo root")


def test_canonical_bar_contract_filters_symbol_and_preserves_trained_fields():
    rows = dataframe_to_canonical_bar_rows(FakeMarketData().df, symbol="AAPL", feed="iex")

    assert_equal(len(rows), 2, "AAPL row count")
    for row in rows:
        assert_true(
            set(CANONICAL_BAR_REQUIRED_FIELDS) <= set(row),
            "required canonical OHLCV/VWAP fields",
        )
        assert_equal(row["timeframe"], CANONICAL_BAR_TIMEFRAME, "timeframe")
        assert_equal(row["adjustment"], "raw", "adjustment")
        assert_equal(row["contract_version"], "canonical_1min_ohlcv_vwap_v1", "contract")


def test_label_features_market_data_uses_canonical_one_minute_contract():
    market_data = FakeMarketData()
    service = LabelFeaturesMarketDataService(market_data=market_data)

    rows = service.fetch_forward_bars(
        symbol="AAPL",
        snapshot_dt=pd.Timestamp("2026-06-10T09:30:00-04:00").to_pydatetime(),
    )

    assert_equal(market_data.calls[0][1], CANONICAL_BAR_TIMEFRAME, "label timeframe")
    assert_equal(market_data.calls[0][2].get("adjustment"), "raw", "label adjustment")
    assert_true("feed" not in market_data.calls[0][2], "label feed follows shared default")
    assert_equal(len(rows), 2, "label rows")
    for field in CANONICAL_BAR_REQUIRED_FIELDS:
        assert_true(rows[0].get(field) is not None, f"label field {field}")


def test_label_features_market_data_accepts_list_bar_responses():
    market_data = FakeListMarketData()
    service = LabelFeaturesMarketDataService(market_data=market_data)

    rows = service.fetch_forward_bars(
        symbol="AAPL",
        snapshot_dt=pd.Timestamp("2026-06-10T09:30:00-04:00").to_pydatetime(),
    )

    assert_equal(len(rows), 1, "label list rows")
    assert_equal(rows[0]["symbol"], "AAPL", "symbol filter")
    assert_true(rows[0]["timestamp"].startswith("2026-06-10T09:30:00"), "timestamp")
    for field in CANONICAL_BAR_REQUIRED_FIELDS:
        assert_true(rows[0].get(field) is not None, f"list label field {field}")


def test_label_features_main_fails_when_all_rows_error():
    original_unlabeled = label_features_script.unlabeled_snapshots
    original_fetch = label_features_script.fetch_forward_bars
    try:
        label_features_script.unlabeled_snapshots = lambda limit=100: [
            {
                "id": 1,
                "symbol": "AAPL",
                "timestamp": "2026-06-10T09:30:00-04:00",
                "last_price": 100.0,
            }
        ]

        def _raise_fetch(symbol, ts):
            raise RuntimeError("market-data adapter failed")

        label_features_script.fetch_forward_bars = _raise_fetch
        assert_equal(label_features_script.main(), 1, "all-error exit code")
    finally:
        label_features_script.unlabeled_snapshots = original_unlabeled
        label_features_script.fetch_forward_bars = original_fetch


if __name__ == "__main__":
    tests = [
        test_label_features_script_uses_repo_root_like_live_features,
        test_canonical_bar_contract_filters_symbol_and_preserves_trained_fields,
        test_label_features_market_data_uses_canonical_one_minute_contract,
        test_label_features_market_data_accepts_list_bar_responses,
        test_label_features_main_fails_when_all_rows_error,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} live/label bar contract tests passed.")
