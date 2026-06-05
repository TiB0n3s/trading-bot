"""Polygon market-data adapter for validation and replay.

This adapter is intentionally not wired into live trading. It gives reports and
future parity checks an independent source for quotes and aggregate bars.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


POLYGON_BASE_URL = "https://api.polygon.io"


@dataclass(frozen=True)
class PolygonRequest:
    path: str
    params: dict[str, Any]

    @property
    def url(self) -> str:
        query = urlencode({k: v for k, v in self.params.items() if v is not None})
        return f"{POLYGON_BASE_URL}{self.path}?{query}" if query else f"{POLYGON_BASE_URL}{self.path}"


class PolygonMarketDataService:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        retry_attempts: int = 0,
        retry_sleep_seconds: float = 15.0,
        transport: Callable[[PolygonRequest], dict[str, Any]] | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("POLYGON_API_KEY", "")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = max(0, int(retry_attempts or 0))
        self.retry_sleep_seconds = max(0.0, float(retry_sleep_seconds or 0.0))
        self.transport = transport or self._default_transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, path: str, **params) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("POLYGON_API_KEY is not configured")
        request = PolygonRequest(path=path, params={**params, "apiKey": self.api_key})
        return self.transport(request)

    def _default_transport(self, request: PolygonRequest) -> dict[str, Any]:
        req = Request(request.url, headers={"User-Agent": "trading-bot/polygon-validation"})
        attempts = self.retry_attempts + 1
        for attempt in range(attempts):
            try:
                with urlopen(req, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code != 429 or attempt >= attempts - 1:
                    raise
                time.sleep(self.retry_sleep_seconds)
        raise RuntimeError("unreachable polygon retry state")

    def latest_quote(self, symbol: str) -> dict[str, Any]:
        """Return Polygon's latest quote payload for a stock symbol."""
        symbol = str(symbol or "").upper().strip()
        return self._request(f"/v2/last/nbbo/{symbol}")

    def aggregate_bars(
        self,
        symbol: str,
        *,
        from_date: str | date,
        to_date: str | date,
        multiplier: int = 1,
        timespan: str = "minute",
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 5000,
    ) -> dict[str, Any]:
        """Return aggregate bars for validation/replay."""
        symbol = str(symbol or "").upper().strip()
        return self._request(
            f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from_date}/{to_date}",
            adjusted=str(bool(adjusted)).lower(),
            sort=sort,
            limit=limit,
        )

    def aggregate_bar_dicts(
        self,
        symbol: str,
        *,
        from_date: str | date,
        to_date: str | date,
        multiplier: int = 5,
        timespan: str = "minute",
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 50000,
    ) -> list[dict[str, Any]]:
        payload = self.aggregate_bars(
            symbol,
            from_date=from_date,
            to_date=to_date,
            multiplier=multiplier,
            timespan=timespan,
            adjusted=adjusted,
            sort=sort,
            limit=limit,
        )
        bars = []
        for row in payload.get("results") or []:
            ts = row.get("t")
            if ts is not None:
                try:
                    timestamp = datetime.fromtimestamp(
                        float(ts) / 1000.0,
                        tz=timezone.utc,
                    ).isoformat()
                except Exception:
                    timestamp = str(ts)
            else:
                timestamp = ""
            bars.append(
                {
                    "timestamp": timestamp,
                    "open": row.get("o"),
                    "high": row.get("h"),
                    "low": row.get("l"),
                    "close": row.get("c"),
                    "volume": row.get("v"),
                    "vwap": row.get("vw") if row.get("vw") is not None else row.get("c"),
                }
            )
        return bars

    def trades(
        self,
        symbol: str,
        *,
        timestamp: str | date,
        order: str = "asc",
        sort: str = "timestamp",
        limit: int = 50000,
    ) -> dict[str, Any]:
        """Return Polygon stock trades for a symbol/date when the key is entitled.

        This uses Polygon's v3 trades endpoint and returns raw payload metadata
        so callers can inspect entitlement/rate-limit behavior.
        """
        symbol = str(symbol or "").upper().strip()
        return self._request(
            f"/v3/trades/{symbol}",
            timestamp=timestamp,
            order=order,
            sort=sort,
            limit=limit,
        )

    def trade_dicts(
        self,
        symbol: str,
        *,
        timestamp: str | date,
        order: str = "asc",
        sort: str = "timestamp",
        limit: int = 50000,
    ) -> list[dict[str, Any]]:
        payload = self.trades(
            symbol,
            timestamp=timestamp,
            order=order,
            sort=sort,
            limit=limit,
        )
        trades = []
        for row in payload.get("results") or []:
            ts = row.get("sip_timestamp") or row.get("participant_timestamp") or row.get("trf_timestamp")
            timestamp_iso = ""
            if ts is not None:
                try:
                    timestamp_iso = datetime.fromtimestamp(
                        float(ts) / 1_000_000_000.0,
                        tz=timezone.utc,
                    ).isoformat()
                except Exception:
                    timestamp_iso = str(ts)
            trades.append(
                {
                    "timestamp": timestamp_iso,
                    "price": row.get("price"),
                    "size": row.get("size"),
                    "exchange": row.get("exchange"),
                    "conditions": row.get("conditions"),
                    "sequence_number": row.get("sequence_number"),
                    "tape": row.get("tape"),
                    "raw": row,
                }
            )
        return trades

    def latest_quote_summary(self, symbol: str) -> dict[str, Any]:
        payload = self.latest_quote(symbol)
        result = payload.get("results") or {}
        bid = result.get("bid_price") or result.get("bp")
        ask = result.get("ask_price") or result.get("ap")
        spread = None
        spread_pct = None
        try:
            bid_f = float(bid)
            ask_f = float(ask)
            mid = (bid_f + ask_f) / 2
            spread = ask_f - bid_f
            spread_pct = spread / mid * 100 if mid else None
        except Exception:
            pass
        return {
            "symbol": str(symbol or "").upper().strip(),
            "provider": "polygon",
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "spread_pct": spread_pct,
            "raw_status": payload.get("status"),
            "raw": payload,
        }
