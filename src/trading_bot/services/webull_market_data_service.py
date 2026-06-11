"""Read-only Webull market-data adapter.

This service is intentionally diagnostic-only. It lets the platform validate
Webull credentials, SDK availability, and quote parity before Webull is allowed
near execution authority.
"""

from __future__ import annotations

import importlib.metadata
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

WEBULL_SDK_PACKAGE = "webull-openapi-python-sdk"
WEBULL_MARKET_DATA_VERSION = "webull_market_data_v1"
WEBULL_SDK_LOGGERS = ("webull",)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WebullCredentials:
    api_key: str
    api_secret: str
    account_id: str
    region: str = "US"
    overnight_required: bool = False
    extended_hours_required: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret and self.account_id)


def webull_credentials_from_env() -> WebullCredentials:
    return WebullCredentials(
        api_key=os.getenv("WEBULL_API_KEY", "") or os.getenv("WEBULL_APP_KEY", ""),
        api_secret=os.getenv("WEBULL_API_SECRET", "") or os.getenv("WEBULL_APP_SECRET", ""),
        account_id=os.getenv("WEBULL_ACCOUNT_ID", ""),
        region=os.getenv("WEBULL_REGION", "US") or "US",
        overnight_required=_env_bool("WEBULL_OVERNIGHT_REQUIRED", False),
        extended_hours_required=_env_bool("WEBULL_EXTENDED_HOURS_REQUIRED", False),
    )


def webull_sdk_version() -> str | None:
    try:
        return importlib.metadata.version(WEBULL_SDK_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return None


def webull_readiness(*, credentials: WebullCredentials | None = None) -> dict[str, Any]:
    credentials = credentials or webull_credentials_from_env()
    sdk_version = webull_sdk_version()
    blockers = []
    if not credentials.configured:
        blockers.append(
            "WEBULL_API_KEY/WEBULL_API_SECRET/WEBULL_ACCOUNT_ID are not fully configured"
        )
    if not sdk_version:
        blockers.append(f"{WEBULL_SDK_PACKAGE} is not installed")
    return {
        "version": WEBULL_MARKET_DATA_VERSION,
        "runtime_effect": "diagnostic_only_no_trade_authority",
        "configured": credentials.configured,
        "sdk_available": bool(sdk_version),
        "sdk_package": WEBULL_SDK_PACKAGE,
        "sdk_version": sdk_version,
        "account_id_present": bool(credentials.account_id),
        "region": credentials.region,
        "overnight_required": credentials.overnight_required,
        "extended_hours_required": credentials.extended_hours_required,
        "status": "ready" if not blockers else "not_ready",
        "blockers": blockers,
    }


class WebullMarketDataService:
    """Adapter around Webull quote clients.

    Production code may inject an official SDK client once the concrete SDK
    object is initialized. The adapter accepts common quote method names so SDK
    version differences stay contained here.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        credentials: WebullCredentials | None = None,
    ):
        self.client = client
        self.credentials = credentials or webull_credentials_from_env()

    @property
    def configured(self) -> bool:
        return self.credentials.configured

    def readiness(self) -> dict[str, Any]:
        payload = webull_readiness(credentials=self.credentials)
        payload["client_injected"] = self.client is not None
        return payload

    def latest_quote_summary(self, symbol: str) -> dict[str, Any]:
        symbol = str(symbol or "").upper().strip()
        if not symbol:
            raise ValueError("symbol is required")
        if self.client is None:
            self.client = self._build_default_client()
        raw = self._call_latest_quote(symbol)
        return _normalize_webull_quote(symbol, raw)

    def _build_default_client(self) -> Any:
        readiness = self.readiness()
        if readiness["status"] != "ready":
            blockers = "; ".join(readiness["blockers"])
            raise RuntimeError(f"Webull market-data client is not ready: {blockers}")
        _silence_webull_sdk_loggers()
        try:
            from webull.core.client import ApiClient  # type: ignore
            from webull.data.data_client import DataClient  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"Webull SDK import failed: {type(exc).__name__}: {exc}") from exc

        with _suppress_webull_sdk_logging():
            api_client = ApiClient(
                self.credentials.api_key,
                self.credentials.api_secret,
                self.credentials.region.lower(),
            )
        return DataClient(api_client)

    def _call_latest_quote(self, symbol: str) -> Any:
        for method_name in (
            "get_latest_quote",
            "latest_quote",
            "get_quote",
            "quote",
            "get_snapshot",
            "snapshot",
        ):
            method = getattr(self.client, method_name, None)
            if callable(method):
                return method(symbol)

        batch_method = getattr(self.client, "get_quotes", None)
        if callable(batch_method):
            payload = batch_method([symbol])
            if isinstance(payload, dict):
                return payload.get(symbol) or payload.get(symbol.upper()) or payload
            if isinstance(payload, list) and payload:
                return payload[0]

        market_data = getattr(self.client, "market_data", None)
        nested_quotes = getattr(market_data, "get_quotes", None)
        if callable(nested_quotes):
            with _suppress_webull_sdk_logging():
                response = nested_quotes(
                    symbol,
                    "US_STOCK",
                    depth=1,
                    overnight_required=self.credentials.overnight_required,
                )
            return _response_payload(response)

        nested_snapshot = getattr(market_data, "get_snapshot", None)
        if callable(nested_snapshot):
            with _suppress_webull_sdk_logging():
                response = nested_snapshot(
                    symbol,
                    "US_STOCK",
                    extend_hour_required=self.credentials.extended_hours_required,
                    overnight_required=self.credentials.overnight_required,
                )
            return _response_payload(response)

        raise RuntimeError("Webull client does not expose a supported quote method")


def _get_first(obj: Any, names: tuple[str, ...]) -> Any:
    if isinstance(obj, dict):
        for name in names:
            if obj.get(name) is not None:
                return obj.get(name)
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _first_depth_price(raw_quote: Any, side: str) -> Any:
    if not isinstance(raw_quote, dict):
        return None
    levels = raw_quote.get(side)
    if not isinstance(levels, list) or not levels:
        return None
    first = levels[0]
    if not isinstance(first, dict):
        return None
    return first.get("price")


def _response_payload(response: Any) -> Any:
    status_code = getattr(response, "status_code", None)
    if status_code is not None and int(status_code) >= 400:
        text = getattr(response, "text", "")
        raise RuntimeError(f"Webull API response status={status_code} body={text}")
    json_method = getattr(response, "json", None)
    if callable(json_method):
        return json_method()
    return response


def _silence_webull_sdk_loggers() -> None:
    for name in WEBULL_SDK_LOGGERS:
        logging.getLogger(name).setLevel(logging.CRITICAL)


@contextmanager
def _suppress_webull_sdk_logging():
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _normalize_webull_quote(symbol: str, raw_quote: Any) -> dict[str, Any]:
    bid = _float_or_none(
        _get_first(raw_quote, ("bid", "bid_price", "bp", "bidPrice", "bid_price_1"))
        or _first_depth_price(raw_quote, "bids")
    )
    ask = _float_or_none(
        _get_first(raw_quote, ("ask", "ask_price", "ap", "askPrice", "ask_price_1"))
        or _first_depth_price(raw_quote, "asks")
    )
    timestamp = _get_first(
        raw_quote,
        ("timestamp", "time", "t", "tradeTime", "quoteTime", "quote_time"),
    )
    spread = ask - bid if bid is not None and ask is not None else None
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread_pct = spread / mid * 100 if spread is not None and mid else None
    return {
        "provider": "webull",
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread": spread,
        "spread_pct": spread_pct,
        "timestamp": str(timestamp) if timestamp is not None else None,
        "available": bid is not None and ask is not None,
        "raw": raw_quote,
    }
