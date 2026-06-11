"""Webull market-data readiness and parity diagnostics."""

from __future__ import annotations

import io
import os
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
from services.webull_rsi_calibration_service import latest_webull_rsi_snapshot


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
    print(f"overnight_required      : {payload['overnight_required']}")
    print(f"extended_hours_required : {payload['extended_hours_required']}")
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


def run_webull_rsi_calibration(symbol: str) -> bool:
    symbol = str(symbol or "").upper().strip()

    print()
    print("=" * 72)
    print(f"  Webull RSI Calibration - {symbol or 'UNKNOWN'}")
    print("=" * 72)
    if not symbol:
        print("[WARN] symbol is required")
        return False

    snapshot = latest_webull_rsi_snapshot(symbol)
    if not snapshot.found:
        print(f"[WARN] {snapshot.reason or 'webull_rsi_snapshot_unavailable'}")
        return False

    observed = float(snapshot.webull_rsi_14 or 0.0)
    expected_text = os.getenv(f"WEBULL_RSI_EXPECTED_{symbol}") or os.getenv("WEBULL_RSI_EXPECTED")
    tolerance = float(os.getenv("WEBULL_RSI_TOLERANCE", "0.75"))
    print("report_version          : webull_rsi_calibration_v1")
    print("runtime_effect          : diagnostic_only_no_live_authority")
    print(f"symbol                  : {symbol}")
    print(f"bar_timestamp           : {snapshot.bar_timestamp}")
    print(f"timeframe               : {snapshot.timeframe}")
    print(f"close                   : {_fmt(snapshot.close)}")
    print(f"webull_rsi_14           : {_fmt(observed)}")
    print(f"webull_rsi_zone         : {snapshot.webull_rsi_zone or '-'}")
    print(f"webull_rsi_exit_signal  : {snapshot.webull_rsi_exit_signal or '-'}")
    print(f"bearish_divergence      : {snapshot.webull_rsi_bearish_divergence}")
    print(f"expected_source         : WEBULL_RSI_EXPECTED_{symbol} or WEBULL_RSI_EXPECTED")
    print(f"tolerance               : {tolerance:.4f}")

    if not expected_text:
        print()
        print("[OK] Webull RSI feature is present; set WEBULL_RSI_EXPECTED to compare app value")
        return True

    expected = float(expected_text)
    delta = abs(observed - expected)
    ok = delta <= tolerance
    print(f"expected_rsi            : {_fmt(expected)}")
    print(f"absolute_delta          : {_fmt(delta)}")
    print()
    print("[OK] Webull RSI within tolerance" if ok else "[WARN] Webull RSI outside tolerance")
    return ok
