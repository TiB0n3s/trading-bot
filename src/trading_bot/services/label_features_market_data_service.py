"""Market-data access for setup feature labeling."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from services.canonical_bar_contract import (
    CANONICAL_BAR_ADJUSTMENT,
    CANONICAL_BAR_TIMEFRAME,
    dataframe_to_canonical_bar_rows,
)
from services.market_data_service import market_data_service


class LabelFeaturesMarketDataService:
    def __init__(self, market_data: Any = market_data_service):
        self.market_data = market_data

    def fetch_forward_bars(self, *, symbol: str, snapshot_dt) -> list[dict]:
        end_dt = snapshot_dt + timedelta(minutes=65)

        bars = self.market_data.get_barset_with_fallback(
            symbol,
            CANONICAL_BAR_TIMEFRAME,
            start=snapshot_dt.isoformat(),
            end=end_dt.isoformat(),
            adjustment=CANONICAL_BAR_ADJUSTMENT,
        )
        feed_used = self.market_data.get_feed_used(symbol) or None
        bars_payload = getattr(bars, "df", bars)
        return dataframe_to_canonical_bar_rows(
            bars_payload,
            symbol=symbol,
            feed=feed_used,
            adjusted=False,
        )


label_features_market_data_service = LabelFeaturesMarketDataService()
