import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.missed_opportunity_service import MissedOpportunityService


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    def load_rejections(self, target_date, symbol=None, category_filter=None, limit=80):
        return self.rows[:limit]


class FakeBar:
    def __init__(self, minute, high, low, close):
        self.t = datetime(2026, 5, 30, 14, 0, tzinfo=timezone.utc) + timedelta(
            minutes=minute
        )
        self.o = close
        self.h = high
        self.l = low
        self.c = close


class FakeMarketData:
    def get_bars_with_fallback(self, *args, **kwargs):
        return [
            FakeBar(0, 100, 99, 100),
            FakeBar(15, 101, 99.5, 101),
            FakeBar(30, 102, 99, 101.5),
            FakeBar(60, 103, 98, 102),
        ]


def _row():
    return {
        "id": 1,
        "timestamp": "2026-05-30T14:00:00+00:00",
        "symbol": "AAPL",
        "signal_price": 100,
        "rejection_reason": "prediction_gate: weak",
        "market_bias": "buy",
        "market_bias_effective": "buy",
        "trend_direction": "bullish",
        "trend_strength": "confirmed",
        "momentum_direction": "rising",
        "momentum_pct": 0.2,
        "session_trend_label": "uptrend",
        "prediction_score": 40,
        "prediction_decision": "block",
        "setup_label": "setup",
        "setup_policy_action": "allow",
        "buy_opportunity_score": 50,
        "buy_opportunity_recommendation": "neutral",
    }


def test_analyze_row_calculates_forward_returns_and_classification():
    service = MissedOpportunityService(
        repository=FakeRepository([_row()]),
        market_data=FakeMarketData(),
    )

    result = service.analyze_row(_row())

    assert result["category"] == "prediction_gate"
    assert result["return_15m_pct"] == 1.0
    assert result["return_30m_pct"] == 1.5
    assert result["mfe_75m_pct"] == 3.0
    assert result["mae_75m_pct"] == -2.0
    assert result["missed_classification"] == "missed_good_trade"


if __name__ == "__main__":
    test_analyze_row_calculates_forward_returns_and_classification()
    print("[OK] test_analyze_row_calculates_forward_returns_and_classification")
    print("\nAll 1 missed opportunity service tests passed.")
