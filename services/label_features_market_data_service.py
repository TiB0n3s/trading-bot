"""Market-data access for setup feature labeling."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from services.market_data_service import market_data_service


class LabelFeaturesMarketDataService:
    def __init__(self, market_data: Any = market_data_service):
        self.market_data = market_data

    def fetch_forward_bars(self, *, symbol: str, snapshot_dt) -> list[dict]:
        end_dt = snapshot_dt + timedelta(minutes=35)

        bars = self.market_data.get_barset_with_fallback(
            symbol,
            "1Min",
            start=snapshot_dt.isoformat(),
            end=end_dt.isoformat(),
            adjustment="raw",
            feed="iex",
        ).df

        if bars is None or bars.empty:
            return []

        if "symbol" in bars.columns:
            bars = bars[bars["symbol"] == symbol]

        rows = []
        for idx, row in bars.iterrows():
            rows.append(
                {
                    "timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                    "close": float(row["close"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                }
            )
        return rows


label_features_market_data_service = LabelFeaturesMarketDataService()
