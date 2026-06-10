"""Compare Alpaca and Polygon market-data snapshots for diagnostics."""

from __future__ import annotations

from typing import Any

MARKET_DATA_PARITY_VERSION = "market_data_parity_v1"


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


def normalize_quote(provider: str, raw_quote: Any) -> dict[str, Any]:
    bid = _float_or_none(_get_first(raw_quote, ("bid", "bid_price", "bp", "bidprice")))
    ask = _float_or_none(_get_first(raw_quote, ("ask", "ask_price", "ap", "askprice")))
    timestamp = _get_first(raw_quote, ("timestamp", "t", "sip_timestamp", "participant_timestamp"))
    spread = ask - bid if bid is not None and ask is not None else None
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread_pct = spread / mid * 100 if spread is not None and mid else None
    return {
        "provider": provider,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread": spread,
        "spread_pct": spread_pct,
        "timestamp": str(timestamp) if timestamp is not None else None,
        "available": bid is not None and ask is not None,
    }


def normalize_bar(raw_bar: Any) -> dict[str, Any]:
    return {
        "open": _float_or_none(_get_first(raw_bar, ("open", "o"))),
        "high": _float_or_none(_get_first(raw_bar, ("high", "h"))),
        "low": _float_or_none(_get_first(raw_bar, ("low", "l"))),
        "close": _float_or_none(_get_first(raw_bar, ("close", "c"))),
        "volume": _float_or_none(_get_first(raw_bar, ("volume", "v"))),
        "timestamp": _get_first(raw_bar, ("timestamp", "t")),
    }


class MarketDataParityService:
    def __init__(self, *, alpaca_market_data: Any, polygon_market_data: Any):
        self.alpaca_market_data = alpaca_market_data
        self.polygon_market_data = polygon_market_data

    def latest_quote_parity(self, symbol: str) -> dict[str, Any]:
        symbol = str(symbol or "").upper().strip()
        alpaca_error = None
        polygon_error = None
        try:
            alpaca_quote = self.alpaca_market_data.get_latest_quote(symbol)
            alpaca = normalize_quote("alpaca", alpaca_quote)
        except Exception as exc:
            alpaca_error = str(exc)
            alpaca = normalize_quote("alpaca", {})

        try:
            polygon = self.polygon_market_data.latest_quote_summary(symbol)
            polygon = normalize_quote("polygon", polygon)
        except Exception as exc:
            polygon_error = str(exc)
            polygon = normalize_quote("polygon", {})

        mid_diff = None
        mid_diff_pct = None
        spread_pct_diff = None
        if alpaca["mid"] is not None and polygon["mid"] is not None:
            mid_diff = alpaca["mid"] - polygon["mid"]
            mid_diff_pct = mid_diff / polygon["mid"] * 100 if polygon["mid"] else None
        if alpaca["spread_pct"] is not None and polygon["spread_pct"] is not None:
            spread_pct_diff = alpaca["spread_pct"] - polygon["spread_pct"]

        status = "ok" if alpaca["available"] and polygon["available"] else "partial"
        if alpaca_error and polygon_error:
            status = "failed"

        return {
            "version": MARKET_DATA_PARITY_VERSION,
            "runtime_effect": "diagnostic_only_no_live_authority",
            "symbol": symbol,
            "status": status,
            "alpaca": alpaca,
            "polygon": polygon,
            "mid_diff": mid_diff,
            "mid_diff_pct": mid_diff_pct,
            "spread_pct_diff": spread_pct_diff,
            "alpaca_error": alpaca_error,
            "polygon_error": polygon_error,
        }

    def daily_bar_parity(self, symbol: str, target_date: str) -> dict[str, Any]:
        symbol = str(symbol or "").upper().strip()
        alpaca_error = None
        polygon_error = None
        try:
            alpaca_bars = self.alpaca_market_data.get_bars_with_fallback(
                symbol,
                "1Day",
                start=target_date,
                end=target_date,
            )
            alpaca_bar = normalize_bar(list(alpaca_bars)[0]) if alpaca_bars else {}
        except Exception as exc:
            alpaca_error = str(exc)
            alpaca_bar = {}

        try:
            polygon_payload = self.polygon_market_data.aggregate_bars(
                symbol,
                from_date=target_date,
                to_date=target_date,
                multiplier=1,
                timespan="day",
            )
            polygon_results = polygon_payload.get("results") or []
            raw = polygon_results[0] if polygon_results else {}
            polygon_bar = normalize_bar(raw)
        except Exception as exc:
            polygon_error = str(exc)
            polygon_bar = {}

        diffs = {}
        for key in ("open", "high", "low", "close", "volume"):
            a_val = _float_or_none(alpaca_bar.get(key))
            p_val = _float_or_none(polygon_bar.get(key))
            diff = a_val - p_val if a_val is not None and p_val is not None else None
            diff_pct = diff / p_val * 100 if diff is not None and p_val else None
            diffs[key] = {
                "alpaca": a_val,
                "polygon": p_val,
                "diff": diff,
                "diff_pct": diff_pct,
            }

        status = "ok" if alpaca_bar and polygon_bar else "partial"
        if alpaca_error and polygon_error:
            status = "failed"
        return {
            "version": MARKET_DATA_PARITY_VERSION,
            "runtime_effect": "diagnostic_only_no_live_authority",
            "symbol": symbol,
            "target_date": target_date,
            "status": status,
            "alpaca": alpaca_bar,
            "polygon": polygon_bar,
            "diffs": diffs,
            "alpaca_error": alpaca_error,
            "polygon_error": polygon_error,
        }
