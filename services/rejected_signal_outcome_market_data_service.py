"""Market-data access for rejected signal outcome labeling."""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from services.market_data_service import market_data_service


class RejectedSignalOutcomeMarketDataService:
    def __init__(self, market_data: Any = market_data_service):
        self.market_data = market_data

    @staticmethod
    def _barset_rows(barset, symbol: str) -> list[dict]:
        bars = barset.df

        if bars is None or bars.empty:
            return []

        if "symbol" in bars.columns:
            bars = bars[bars["symbol"] == symbol]

        rows = []
        for idx, bar in bars.iterrows():
            rows.append(
                {
                    "timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                    "close": float(bar["close"]),
                    "high": float(bar["high"]),
                    "low": float(bar["low"]),
                }
            )
        return rows

    def fetch_forward_bars(
        self,
        *,
        symbol: str,
        signal_dt,
        market_close_dt,
    ) -> list[dict]:
        end_dt = max(signal_dt + timedelta(minutes=65), market_close_dt)

        barset = self.market_data.get_barset_with_fallback(
            symbol,
            "1Min",
            start=signal_dt.isoformat(),
            end=end_dt.isoformat(),
            adjustment="raw",
            feed=os.getenv("ALPACA_BARS_FEED", "iex"),
        )
        return self._barset_rows(barset, symbol)

    def fetch_day_bars(self, *, symbol: str, start_dt, end_dt) -> list[dict]:
        barset = self.market_data.get_barset_with_fallback(
            symbol,
            "1Min",
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
            adjustment="raw",
            feed=os.getenv("ALPACA_BARS_FEED", "iex"),
        )
        return self._barset_rows(barset, symbol)


rejected_signal_outcome_market_data_service = RejectedSignalOutcomeMarketDataService()
