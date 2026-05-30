#!/usr/bin/env python3

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.portfolio_rotation_service import PortfolioRotationService


class FakeLog:
    def error(self, message):
        self.last_error = message

    def warning(self, message):
        self.last_warning = message


class FakeTrades:
    def portfolio_rotation_count_today(self):
        return 0


class FakeBroker:
    def __init__(self, positions=()):
        self.positions = list(positions)

    def list_positions(self):
        return self.positions

    def place_order(self, **kwargs):
        return {"order_id": "rotation-order", **kwargs}


def _service(**overrides):
    defaults = {
        "broker_service": FakeBroker(),
        "trades_repo": FakeTrades(),
        "trend_table": {"AAPL": {"direction": "bullish", "strength": "confirmed"}},
        "market_bias": {
            "AAPL": {
                "bias": "buy",
                "risk_level": "medium",
                "entry_quality": "excellent",
            }
        },
        "open_entry_context": lambda symbol: {"holding_minutes": 60},
        "log_trade": lambda **kwargs: None,
        "last_order": {},
        "write_cooldown": lambda *args, **kwargs: None,
        "last_sell": {},
        "write_recent_sell": lambda *args, **kwargs: None,
        "enabled": True,
        "max_per_day": 2,
        "min_candidate_score": 12,
        "min_hold_minutes": 30,
        "max_weak_plpc": 0.0,
        "excluded_symbols": {"SPY"},
        "allowed_risk_levels": {"low", "medium"},
        "allowed_entry_qualities": {"excellent"},
        "log": FakeLog(),
    }
    defaults.update(overrides)
    return PortfolioRotationService(**defaults)


def test_candidate_score_accepts_strong_buy_bias_context():
    score, reason = _service().candidate_score(
        "AAPL",
        {"momentum": {"direction": "rising"}},
    )

    assert score == 18
    assert "bullish/confirmed" in reason
    assert "buy bias" in reason


def test_weakest_rotation_holding_filters_and_sorts():
    positions = [
        SimpleNamespace(
            symbol="MSFT",
            qty="2",
            unrealized_plpc="-0.01",
            current_price="100",
        ),
        SimpleNamespace(
            symbol="NVDA",
            qty="2",
            unrealized_plpc="-0.03",
            current_price="200",
        ),
    ]
    service = _service(
        broker_service=FakeBroker(positions),
        trend_table={
            "MSFT": {"direction": "neutral", "strength": "weak"},
            "NVDA": {"direction": "bearish", "strength": "developing"},
        },
    )

    weakest = service.weakest_rotation_holding("AAPL")

    assert weakest["symbol"] == "NVDA"
    assert weakest["unrealized_plpc"] == -3.0


def test_weakest_position_context_uses_lowest_unrealized_plpc():
    weakest = _service().weakest_position_context(
        {
            "open_positions": [
                {"symbol": "AAPL", "unrealized_plpc": 2.0, "market_value": 1000},
                {"symbol": "MSFT", "unrealized_plpc": -1.5, "market_value": 900},
            ]
        }
    )

    assert weakest["symbol"] == "MSFT"
    assert weakest["weakness_score"] == -1.5


def main():
    tests = [
        test_candidate_score_accepts_strong_buy_bias_context,
        test_weakest_rotation_holding_filters_and_sorts,
        test_weakest_position_context_uses_lowest_unrealized_plpc,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nAll 3 portfolio rotation service tests passed.")


if __name__ == "__main__":
    main()
