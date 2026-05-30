from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.market_context_service import MarketContextService
from services.symbol_override_service import SymbolOverrideService
from services.trend_state_service import TrendStateService


class FakeLog:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))

    def debug(self, message):
        self.messages.append(("debug", message))


def test_symbol_override_service_loads_and_blocks():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "symbol_overrides.json"
        path.write_text(
            json.dumps(
                {
                    "disabled_symbols": ["msft"],
                    "buy_disabled": ["aapl"],
                    "sell_only": ["nvda"],
                    "notes": {"AAPL": "pause buys"},
                }
            )
        )
        overrides = {}
        service = SymbolOverrideService(path=path, overrides=overrides, log=FakeLog())

        assert service.block_reason("AAPL", "buy") == (
            "BUY disabled by operator override — pause buys"
        )
        assert service.block_reason("NVDA", "buy") == (
            "symbol in sell_only mode by operator override"
        )
        assert service.block_reason("MSFT", "sell") == (
            "symbol disabled by operator override"
        )
        assert service.block_reason("AAPL", "sell") is None
        assert overrides["buy_disabled"] == ["AAPL"]


def test_market_context_service_loads_same_day_bias_and_clears_stale():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "market_context.json"
        path.write_text(
            json.dumps(
                {
                    "market_date": "2026-05-30",
                    "macro_sentiment": "risk_on",
                    "symbols": {"AAPL": {"bias": "buy"}},
                }
            )
        )
        market_bias = {}
        service = MarketContextService(
            path=path,
            market_bias=market_bias,
            expected_market_context_date=lambda: date(2026, 5, 30),
            log=FakeLog(),
        )

        service.load()
        assert market_bias["AAPL"]["bias"] == "buy"
        assert market_bias["AAPL"]["risk_level"] is None

        service.mtime = 0
        path.write_text(json.dumps({"market_date": "2026-05-29", "symbols": {}}))
        service.load()
        assert market_bias == {}


def test_trend_state_service_builds_refreshes_and_updates():
    class Repo:
        def recent_signal_history(self, approved):
            assert approved == ["AAPL", "MSFT"]
            return [
                ("AAPL", "buy", "2026-05-30 09:31:00"),
                ("AAPL", "buy", "2026-05-30 09:32:00"),
            ]

        def recent_actions_for_trend(self, symbol):
            assert symbol == "AAPL"
            return [("buy",), ("buy",)]

    signal_history = {}
    trend_table = {}
    service = TrendStateService(
        approved_symbols={"AAPL", "MSFT"},
        signal_history=signal_history,
        trend_table=trend_table,
        trades_repo=Repo(),
        market_bias={},
        symbol_market_alignment_map={},
        load_market_context=lambda: None,
        log=FakeLog(),
    )

    service.build_table()
    assert trend_table["AAPL"]["direction"] == "bullish"
    assert trend_table["MSFT"]["direction"] == "neutral"

    service.update_history("AAPL", "buy")
    assert signal_history["AAPL"][0] == "buy"
    assert trend_table["AAPL"]["last_signal"] == "buy"


def main():
    tests = [
        test_symbol_override_service_loads_and_blocks,
        test_market_context_service_loads_same_day_bias_and_clears_stale,
        test_trend_state_service_builds_refreshes_and_updates,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nAll 3 runtime state service tests passed.")


if __name__ == "__main__":
    main()
