"""Centralized live tape reads."""

from __future__ import annotations

from typing import Any

from market_intelligence.intraday_state import build_intraday_state
from market_intelligence.tape_reader import classify_tape
from services.market_data_service import MarketDataService


class TapeService:
    def __init__(self, market_data: MarketDataService):
        self.market_data = market_data

    def build_tape_context(
        self,
        symbol: str,
        current_price: float | None = None,
        lookback_minutes: int = 90,
    ) -> dict[str, Any]:
        symbol = str(symbol or "").strip().upper()

        try:
            bars = self.market_data.get_recent_bar_dicts(
                symbol,
                lookback_minutes=lookback_minutes,
                timeframe="1Min",
                feed="sip",
            )
            state = build_intraday_state(
                symbol=symbol,
                bars=bars,
                current_price=current_price,
            )
            classification = classify_tape(state)

            return {
                "symbol": symbol,
                "ok": True,
                "bar_count": len(bars),
                "feed_used": self.market_data.get_feed_used(symbol),
                "state": state,
                "classification": classification,
            }
        except Exception as exc:
            return {
                "symbol": symbol,
                "ok": False,
                "error": str(exc),
                "bar_count": 0,
                "feed_used": self.market_data.get_feed_used(symbol),
                "state": None,
                "classification": None,
            }
