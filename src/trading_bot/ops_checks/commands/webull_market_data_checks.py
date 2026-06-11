"""Webull market-data readiness and parity diagnostics."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from services.market_data_parity_service import MarketDataParityService
from services.market_data_service import MarketDataService
from services.polygon_market_data_service import PolygonMarketDataService
from services.webull_market_data_service import (
    WebullMarketDataService,
    _suppress_webull_sdk_logging,
    webull_readiness,
)


def _fmt(value: Any, digits: int = 4) -> str:
    try:
        if value is None:
            return "-"
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def run_webull_readiness() -> bool:
    payload = webull_readiness()

    print()
    print("=" * 72)
    print("  Webull Integration Readiness")
    print("=" * 72)
    print(f"report_version          : {payload['version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"status                  : {payload['status']}")
    print(f"configured              : {payload['configured']}")
    print(f"sdk_available           : {payload['sdk_available']}")
    print(f"sdk_package             : {payload['sdk_package']}")
    print(f"sdk_version             : {payload['sdk_version'] or '-'}")
    print(f"account_id_present      : {payload['account_id_present']}")
    print(f"region                  : {payload['region']}")
    if payload["blockers"]:
        print()
        print("Blockers")
        for blocker in payload["blockers"]:
            print(f"  - {blocker}")
    print()
    print(
        "[OK] Webull adapter ready"
        if payload["status"] == "ready"
        else "[WARN] Webull adapter not ready"
    )
    return payload["status"] == "ready"


def run_webull_market_data_parity(symbol: str) -> bool:
    symbol = str(symbol or "").upper().strip()

    print()
    print("=" * 72)
    print(f"  Webull Market Data Parity - {symbol or 'UNKNOWN'}")
    print("=" * 72)
    if not symbol:
        print("[WARN] symbol is required")
        return False

    service = MarketDataParityService(
        alpaca_market_data=MarketDataService(),
        polygon_market_data=PolygonMarketDataService(),
        webull_market_data=WebullMarketDataService(),
    )
    with (
        _suppress_webull_sdk_logging(),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        payload = service.latest_quote_provider_parity(symbol)

    print(f"report_version          : {payload['version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"status                  : {payload['status']}")
    print()
    print("Quote comparison")
    print(f"  {'provider':<10} {'bid':>12} {'ask':>12} {'mid':>12} {'spread%':>10}")
    print(f"  {'-' * 10} {'-' * 12} {'-' * 12} {'-' * 12} {'-' * 10}")
    for provider in ("alpaca", "polygon", "webull"):
        row = payload["providers"][provider]
        print(
            f"  {provider:<10} "
            f"{_fmt(row['bid']):>12} "
            f"{_fmt(row['ask']):>12} "
            f"{_fmt(row['mid']):>12} "
            f"{_fmt(row['spread_pct']):>10}"
        )
    print()
    print(f"mid_range               : {_fmt(payload['mid_range'])}")
    print(f"mid_range_pct           : {_fmt(payload['mid_range_pct'])}")

    for key in ("alpaca_error", "polygon_error", "webull_error"):
        if payload.get(key):
            print(f"{key:<24}: {payload[key]}")

    ok = payload["status"] == "ok"
    print()
    print("[OK] provider quote parity available" if ok else "[WARN] provider quote parity partial")
    return ok
