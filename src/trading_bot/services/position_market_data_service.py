"""Market-data adapter for position-management reviews."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from services.market_data_service import market_data_service


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class PositionMarketDataService:
    def __init__(self, market_data: Any = market_data_service):
        self.market_data = market_data

    def fetch_intraday_bars(self, symbol: str, minutes: int = 60) -> list[dict[str, Any]]:
        start = (now_utc() - timedelta(minutes=minutes + 5)).isoformat()
        # Keep requests bounded so one slow symbol does not stall the full position review.
        bars = self.market_data.get_bars_with_fallback(
            symbol,
            "1Min",
            start=start,
            feed="iex",
            limit=minutes + 10,
        )

        out = []
        for bar in bars:
            try:
                out.append(
                    {
                        "timestamp": bar.t.isoformat(),
                        "open": float(bar.o),
                        "high": float(bar.h),
                        "low": float(bar.l),
                        "close": float(bar.c),
                        "volume": float(getattr(bar, "v", 0) or 0),
                    }
                )
            except Exception:
                continue

        return out


position_market_data_service = PositionMarketDataService()
