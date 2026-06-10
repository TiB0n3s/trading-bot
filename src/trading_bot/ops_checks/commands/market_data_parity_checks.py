"""Operator report for Alpaca-vs-Polygon market-data parity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.market_data_parity_service import MarketDataParityService
from services.market_data_service import MarketDataService
from services.polygon_market_data_service import PolygonMarketDataService


def _fmt(value: Any, digits: int = 4) -> str:
    try:
        if value is None:
            return "-"
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def run_market_data_parity(
    symbol: str,
    *,
    base_dir: Path,
    mode: str = "quote",
    target_date: str | None = None,
) -> bool:
    symbol = str(symbol or "").upper().strip()

    print()
    print("=" * 72)
    print(f"  Market Data Parity - {symbol or 'UNKNOWN'}")
    print("=" * 72)

    if not symbol:
        print("[WARN] symbol is required")
        return False

    service = MarketDataParityService(
        alpaca_market_data=MarketDataService(),
        polygon_market_data=PolygonMarketDataService(),
    )
    if mode == "bars":
        if not target_date:
            print("[WARN] --date is required for --bars mode")
            return False
        payload = service.daily_bar_parity(symbol, target_date)
        print(f"report_version          : {payload['version']}")
        print(f"runtime_effect          : {payload['runtime_effect']}")
        print("mode                    : daily_bars")
        print(f"date                    : {target_date}")
        print(f"status                  : {payload['status']}")

        print()
        print("Daily bar comparison")
        print(f"  {'field':<8} {'alpaca':>12} {'polygon':>12} {'diff':>12} {'diff%':>10}")
        print(f"  {'-' * 8} {'-' * 12} {'-' * 12} {'-' * 12} {'-' * 10}")
        for field, row in payload["diffs"].items():
            print(
                f"  {field:<8} "
                f"{_fmt(row['alpaca']):>12} "
                f"{_fmt(row['polygon']):>12} "
                f"{_fmt(row['diff']):>12} "
                f"{_fmt(row['diff_pct']):>10}"
            )

        if payload.get("alpaca_error"):
            print(f"alpaca_error            : {payload['alpaca_error']}")
        if payload.get("polygon_error"):
            print(f"polygon_error           : {payload['polygon_error']}")
        ok = payload["status"] == "ok"
        print()
        print(
            "[OK] market data bar parity available"
            if ok
            else "[WARN] market data bar parity incomplete"
        )
        return ok

    payload = service.latest_quote_parity(symbol)

    print(f"report_version          : {payload['version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"status                  : {payload['status']}")

    print()
    print("Quote comparison")
    print(f"  {'provider':<10} {'bid':>12} {'ask':>12} {'mid':>12} {'spread%':>10}")
    print(f"  {'-' * 10} {'-' * 12} {'-' * 12} {'-' * 12} {'-' * 10}")
    for provider in ("alpaca", "polygon"):
        row = payload[provider]
        print(
            f"  {provider:<10} "
            f"{_fmt(row['bid']):>12} "
            f"{_fmt(row['ask']):>12} "
            f"{_fmt(row['mid']):>12} "
            f"{_fmt(row['spread_pct']):>10}"
        )

    print()
    print(f"mid_diff                : {_fmt(payload['mid_diff'])}")
    print(f"mid_diff_pct            : {_fmt(payload['mid_diff_pct'])}")
    print(f"spread_pct_diff         : {_fmt(payload['spread_pct_diff'])}")

    if payload.get("alpaca_error"):
        print(f"alpaca_error            : {payload['alpaca_error']}")
    if payload.get("polygon_error"):
        print(f"polygon_error           : {payload['polygon_error']}")

    ok = payload["status"] == "ok"
    print()
    print("[OK] market data parity available" if ok else "[WARN] market data parity incomplete")
    return ok
