"""Live quote quality diagnostics across market-data providers."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from services.live_quote_quality_service import LiveQuoteQualityService
from services.market_data_parity_service import MarketDataParityService
from services.market_data_service import MarketDataService
from services.polygon_market_data_service import PolygonMarketDataService
from services.webull_market_data_service import (
    WebullMarketDataService,
    _suppress_webull_sdk_logging,
)


def _fmt(value: Any, digits: int = 4) -> str:
    try:
        if value is None:
            return "-"
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def run_live_quote_quality(symbol: str) -> bool:
    symbol = str(symbol or "").upper().strip()

    print()
    print("=" * 72)
    print(f"  Live Quote Quality - {symbol or 'UNKNOWN'}")
    print("=" * 72)
    if not symbol:
        print("[WARN] symbol is required")
        return False

    service = LiveQuoteQualityService(
        MarketDataParityService(
            alpaca_market_data=MarketDataService(),
            polygon_market_data=PolygonMarketDataService(),
            webull_market_data=WebullMarketDataService(),
        )
    )
    with (
        _suppress_webull_sdk_logging(),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        report = service.assess(symbol)
    payload = report.to_dict()

    print(f"report_version          : {payload['version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"status                  : {payload['status']}")
    print(f"available_provider_count: {payload['available_provider_count']}")
    print(f"available_providers     : {', '.join(payload['available_providers']) or '-'}")
    print(f"unavailable_providers   : {', '.join(payload['unavailable_providers']) or '-'}")
    print(f"mid_range_pct           : {_fmt(payload['mid_range_pct'])}")
    print(f"max_provider_spread_pct : {_fmt(payload['max_provider_spread_pct'])}")
    print()
    print("Thresholds")
    for key, value in payload["thresholds"].items():
        print(f"  {key:<28} {value}")
    if payload["blockers"]:
        print()
        print("Blockers")
        for blocker in payload["blockers"]:
            print(f"  - {blocker}")
    if payload["provider_errors"]:
        print()
        print("Provider errors")
        for provider, error in payload["provider_errors"].items():
            print(f"  {provider}: {error}")

    print()
    print(
        "[OK] live quote quality is usable"
        if report.ok
        else "[WARN] live quote quality is degraded"
    )
    return report.ok
