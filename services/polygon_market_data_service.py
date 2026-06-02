"""Polygon market-data adapter for validation and replay.

This adapter is intentionally not wired into live trading. It gives reports and
future parity checks an independent source for quotes and aggregate bars.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable
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
        transport: Callable[[PolygonRequest], dict[str, Any]] | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("POLYGON_API_KEY", "")
        self.timeout_seconds = timeout_seconds
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
        with urlopen(req, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

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
