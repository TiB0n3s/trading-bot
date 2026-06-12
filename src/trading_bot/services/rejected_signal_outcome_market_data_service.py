"""Market-data access for rejected signal outcome labeling."""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from services.canonical_bar_contract import dataframe_to_canonical_bar_rows
from services.market_data_service import market_data_service


class RejectedSignalOutcomeMarketDataService:
    def __init__(self, market_data: Any = market_data_service):
        self.market_data = market_data

    @staticmethod
    def _barset_rows(barset, symbol: str) -> list[dict]:
        bars_payload = getattr(barset, "df", barset)
        return dataframe_to_canonical_bar_rows(bars_payload, symbol=symbol)

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
