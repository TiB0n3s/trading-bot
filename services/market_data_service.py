"""Centralized market-data access.

All app-level Alpaca market-data reads should go through this module so feed
fallback behavior and feed telemetry stay in one place.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from broker import api
from services.observability import record_market_data_fetch

logger = logging.getLogger(__name__)


def bar_to_dict(bar: Any) -> dict[str, Any]:
    """Convert an Alpaca bar object into the dict shape used by intelligence code."""
    return {
        "open": float(getattr(bar, "o", getattr(bar, "open", 0)) or 0),
        "high": float(getattr(bar, "h", getattr(bar, "high", 0)) or 0),
        "low": float(getattr(bar, "l", getattr(bar, "low", 0)) or 0),
        "close": float(getattr(bar, "c", getattr(bar, "close", 0)) or 0),
        "volume": float(getattr(bar, "v", getattr(bar, "volume", 0)) or 0),
        "timestamp": str(getattr(bar, "t", getattr(bar, "timestamp", "")) or ""),
    }


class MarketDataService:
    def __init__(self, client: Any = api, log: logging.Logger | None = None):
        self.client = client
        self.logger = log or logger
        self.last_feed_used: dict[str, str] = {}

    def get_bars_with_fallback(self, symbol: str, timeframe: str, **kwargs) -> list[Any]:
        barset = self.get_barset_with_fallback(symbol, timeframe, **kwargs)
        return list(barset)

    def get_barset_with_fallback(self, symbol: str, timeframe: str, **kwargs) -> Any:
        """Fetch bars using SIP first, with IEX fallback for subscription failures."""
        symbol = str(symbol or "").strip().upper()
        feed = kwargs.pop("feed", "sip")
        try:
            bars = self.client.get_bars(symbol, timeframe, feed=feed, **kwargs)
            self.last_feed_used[symbol] = feed
            record_market_data_fetch(symbol, feed, fallback=False)
            return bars
        except Exception as exc:
            err_lower = str(exc).lower()
            if feed == "sip" and any(
                token in err_lower
                for token in ("subscription", "not permitted", "forbidden", "403")
            ):
                self.logger.warning(
                    f"{symbol}: SIP feed unavailable ({type(exc).__name__}); falling back to IEX"
                )
                bars = self.client.get_bars(symbol, timeframe, feed="iex", **kwargs)
                self.last_feed_used[symbol] = "iex"
                record_market_data_fetch(symbol, "iex", fallback=True)
                return bars
            raise

    def get_recent_bar_dicts(
        self,
        symbol: str,
        lookback_minutes: int = 90,
        timeframe: str = "1Min",
        feed: str = "sip",
    ) -> list[dict[str, Any]]:
        start = (datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)).isoformat()
        bars = self.get_bars_with_fallback(symbol, timeframe, start=start, feed=feed)
        return [bar_to_dict(bar) for bar in bars]

    def get_latest_quote(self, symbol: str) -> Any:
        return self.client.get_latest_quote(str(symbol or "").strip().upper())

    def get_latest_trade(self, symbol: str) -> Any:
        return self.client.get_latest_trade(str(symbol or "").strip().upper())

    def get_feed_used(self, symbol: str) -> str | None:
        return self.last_feed_used.get(str(symbol or "").strip().upper())


_default_market_data_service: MarketDataService | None = None


def get_default_market_data_service() -> MarketDataService:
    global _default_market_data_service
    if _default_market_data_service is None:
        _default_market_data_service = MarketDataService()
    return _default_market_data_service


class _MarketDataServiceProxy:
    """Backward-compatible lazy proxy for scripts not yet using the container."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_default_market_data_service(), name)


market_data_service = _MarketDataServiceProxy()
