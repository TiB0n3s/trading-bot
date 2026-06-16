"""Centralized market-data access.

All app-level Alpaca market-data reads should go through this module so feed
fallback behavior and feed telemetry stay in one place.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from broker import api
from services.observability import record_market_data_fetch

logger = logging.getLogger(__name__)
DEFAULT_BAR_FEED = os.getenv("MARKET_DATA_BAR_FEED", "iex").strip().lower() or "iex"


_BAR_NAME_PAIRS = (
    ("t", "timestamp"),
    ("o", "open"),
    ("h", "high"),
    ("l", "low"),
    ("c", "close"),
    ("v", "volume"),
    ("n", "trade_count"),
    ("vw", "vwap"),
)
_BAR_ALIAS: dict[str, str] = {}
for _short, _full in _BAR_NAME_PAIRS:
    _BAR_ALIAS[_short] = _full
    _BAR_ALIAS[_full] = _short


class _NormalizedBar:
    """Expose Alpaca SDK bars through both short and full attribute names."""

    __slots__ = ("_bar",)

    def __init__(self, bar: Any) -> None:
        self._bar = bar

    def __getattr__(self, name: str) -> Any:
        bar = object.__getattribute__(self, "_bar")
        marker = object()

        if isinstance(bar, dict):
            value = bar.get(name, marker)
        else:
            value = getattr(bar, name, marker)
        if value is not marker:
            return value

        alias = _BAR_ALIAS.get(name)
        if alias is not None:
            if isinstance(bar, dict):
                value = bar.get(alias, marker)
            else:
                value = getattr(bar, alias, marker)
            if value is not marker:
                return value

        raise AttributeError(name)


def _normalize_bar(bar: Any) -> Any:
    if isinstance(bar, (str, bytes, int, float, bool, type(None))):
        return bar
    return bar if isinstance(bar, _NormalizedBar) else _NormalizedBar(bar)


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
        return [_normalize_bar(bar) for bar in barset]

    def get_barset_with_fallback(self, symbol: str, timeframe: str, **kwargs) -> Any:
        """Fetch bars using SIP first, with IEX fallback for subscription failures."""
        symbol = str(symbol or "").strip().upper()
        feed = str(kwargs.pop("feed", None) or DEFAULT_BAR_FEED).strip().lower()
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
