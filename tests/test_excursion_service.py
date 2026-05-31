import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.excursion_service import ExcursionService, classify_trade


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    def load_matched_trades(self, target_date=None, symbol=None, limit=100):
        return self.rows[:limit]


class FakeBar:
    def __init__(self, high, low, close):
        self.t = datetime(2026, 5, 30, 15, 0, tzinfo=timezone.utc)
        self.o = close
        self.h = high
        self.l = low
        self.c = close


class FakeMarketData:
    def get_bars_with_fallback(self, *args, **kwargs):
        return [FakeBar(106, 98, 104), FakeBar(108, 99, 107)]


def _row():
    return {
        "id": 1,
        "symbol": "AAPL",
        "entry_timestamp": "2026-05-30T14:55:00+00:00",
        "exit_timestamp": "2026-05-30T15:05:00+00:00",
        "holding_minutes": 10,
        "qty": 2,
        "entry_price": 100,
        "exit_price": 105,
        "realized_pnl": 10,
        "realized_pnl_pct": 5,
        "market_bias": "buy",
        "market_bias_effective": "buy",
        "trend_direction": "bullish",
        "trend_strength": "confirmed",
        "session_trend_label": "uptrend",
        "prediction_decision": "pass",
        "setup_label": "setup",
        "setup_policy_action": "allow",
        "buy_opportunity_recommendation": "candidate",
    }


def test_analyze_trade_uses_market_data_and_classifies():
    service = ExcursionService(
        repository=FakeRepository([_row()]),
        market_data=FakeMarketData(),
    )

    result = service.analyze_trade(_row())

    assert result["mfe_pct"] == 8.0
    assert result["mae_pct"] == -2.0
    assert result["mfe_dollars"] == 16
    assert result["profit_giveback_pct"] == 37.5
    assert result["excursion_classification"] == "good_trade"


def test_analyze_trades_loads_repository_rows():
    service = ExcursionService(
        repository=FakeRepository([_row()]),
        market_data=FakeMarketData(),
    )

    rows, results = service.analyze_trades(target_date="2026-05-30", limit=1)

    assert len(rows) == 1
    assert len(results) == 1
    assert results[0]["symbol"] == "AAPL"


def test_classify_trade_preserves_winner_became_loser_bucket():
    row = {"realized_pnl": -1}

    assert classify_trade(row, mfe_pct=0.75, mae_pct=-0.2, giveback_pct=None) == (
        "winner_became_loser"
    )


if __name__ == "__main__":
    tests = [
        test_analyze_trade_uses_market_data_and_classifies,
        test_analyze_trades_loads_repository_rows,
        test_classify_trade_preserves_winner_became_loser_bucket,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} excursion service tests passed.")
