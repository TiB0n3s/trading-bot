"""Compatibility adapter exposing the legacy broker REST shape via alpaca-py."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def _as_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**value)
    return value


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw).lower()


def _order_side(value: Any) -> OrderSide:
    normalized = str(value or "").lower()
    return OrderSide.BUY if normalized == "buy" else OrderSide.SELL


def _time_in_force(value: Any) -> TimeInForce:
    normalized = str(value or "").lower()
    if normalized == "gtc":
        return TimeInForce.GTC
    if normalized == "opg":
        return TimeInForce.OPG
    if normalized == "cls":
        return TimeInForce.CLS
    if normalized == "ioc":
        return TimeInForce.IOC
    if normalized == "fok":
        return TimeInForce.FOK
    return TimeInForce.DAY


def _order_class(value: Any) -> OrderClass | None:
    normalized = str(value or "").lower()
    if normalized == "bracket":
        return OrderClass.BRACKET
    if normalized == "oto":
        return OrderClass.OTO
    if normalized == "oco":
        return OrderClass.OCO
    return None


def _query_order_status(value: Any) -> QueryOrderStatus | None:
    normalized = str(value or "").lower()
    if normalized == "open":
        return QueryOrderStatus.OPEN
    if normalized == "closed":
        return QueryOrderStatus.CLOSED
    if normalized == "all":
        return QueryOrderStatus.ALL
    return None


def _data_feed(value: Any) -> DataFeed | None:
    normalized = str(value or "").lower()
    if normalized == "iex":
        return DataFeed.IEX
    if normalized == "sip":
        return DataFeed.SIP
    return None


def _timeframe(value: Any) -> TimeFrame:
    normalized = str(value or "").lower()
    if normalized in {"1min", "1minute", "minute"}:
        return TimeFrame.Minute
    if normalized in {"1hour", "1h", "hour"}:
        return TimeFrame.Hour
    if normalized in {"1day", "1d", "day"}:
        return TimeFrame.Day
    return TimeFrame.Minute


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


class AlpacaPyBrokerAdapter:
    """Small legacy-shape facade around Alpaca's current SDK.

    The rest of the bot still calls methods named like ``get_account`` and
    ``submit_order(**kwargs)``. This adapter keeps that boundary stable while
    moving the backing SDK to alpaca-py.
    """

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        base_url: str,
        trading_client: TradingClient | None = None,
        data_client: StockHistoricalDataClient | None = None,
    ):
        paper = base_url.rstrip("/") == PAPER_BASE_URL
        self.trading_client = trading_client or TradingClient(
            api_key,
            secret_key,
            paper=paper,
            url_override=None if paper else base_url,
        )
        self.data_client = data_client or StockHistoricalDataClient(api_key, secret_key)

    def get_account(self) -> Any:
        return _as_obj(self.trading_client.get_account())

    def get_position(self, symbol: str) -> Any:
        return _as_obj(self.trading_client.get_open_position(str(symbol or "").upper()))

    def list_positions(self) -> list[Any]:
        return [_as_obj(position) for position in self.trading_client.get_all_positions()]

    def list_orders(
        self, status: str = "open", symbols: list[str] | None = None, **kwargs
    ) -> list[Any]:
        request = GetOrdersRequest(
            status=_query_order_status(status),
            symbols=[str(symbol).upper() for symbol in symbols] if symbols else None,
            limit=kwargs.get("limit"),
            nested=kwargs.get("nested"),
        )
        return [_as_obj(order) for order in self.trading_client.get_orders(filter=request)]

    def cancel_order(self, order_id: str) -> Any:
        return self.trading_client.cancel_order_by_id(order_id)

    def get_order(self, order_id: str) -> Any:
        return _as_obj(self.trading_client.get_order_by_id(order_id))

    def submit_order(self, **kwargs) -> Any:
        request = MarketOrderRequest(
            symbol=str(kwargs["symbol"]).upper(),
            qty=kwargs.get("qty"),
            side=_order_side(kwargs.get("side")),
            time_in_force=_time_in_force(kwargs.get("time_in_force")),
            order_class=_order_class(kwargs.get("order_class")),
            client_order_id=kwargs.get("client_order_id"),
            stop_loss=kwargs.get("stop_loss"),
            take_profit=kwargs.get("take_profit"),
        )
        return _as_obj(self.trading_client.submit_order(order_data=request))

    def get_latest_trade(self, symbol: str) -> Any:
        symbol = str(symbol or "").upper()
        request = StockLatestTradeRequest(symbol_or_symbols=symbol)
        response = self.data_client.get_stock_latest_trade(request)
        if isinstance(response, dict):
            return _as_obj(response.get(symbol) or response.get(symbol.lower()) or response)
        return _as_obj(response)

    def get_latest_quote(self, symbol: str) -> Any:
        symbol = str(symbol or "").upper()
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        response = self.data_client.get_stock_latest_quote(request)
        if isinstance(response, dict):
            return _as_obj(response.get(symbol) or response.get(symbol.lower()) or response)
        return _as_obj(response)

    def get_bars(self, symbol: str, timeframe: str, **kwargs) -> list[Any]:
        symbol = str(symbol or "").upper()
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=_timeframe(timeframe),
            start=_datetime_or_none(kwargs.get("start")),
            end=_datetime_or_none(kwargs.get("end")),
            limit=kwargs.get("limit"),
            feed=_data_feed(kwargs.get("feed")),
        )
        response = self.data_client.get_stock_bars(request)
        data = getattr(response, "data", response)
        if isinstance(data, dict):
            bars = data.get(symbol) or data.get(symbol.lower()) or []
            return [_as_obj(bar) for bar in bars]
        return [_as_obj(bar) for bar in data]
