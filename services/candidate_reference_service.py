"""Decision-time reference price capture for candidate learning."""

from __future__ import annotations

from typing import Any

from services.market_data_service import market_data_service


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _quote_attr(quote: Any, *names: str) -> Any:
    for name in names:
        if isinstance(quote, dict) and name in quote:
            return quote.get(name)
        value = getattr(quote, name, None)
        if value is not None:
            return value
    return None


class CandidateReferenceService:
    def __init__(self, market_data: Any = market_data_service):
        self.market_data = market_data

    def candidate_reference_snapshot(self, symbol: str) -> dict[str, Any]:
        """Capture live executable-price context for candidate outcome learning."""
        try:
            quote = self.market_data.get_latest_quote(symbol)
        except Exception as exc:
            return {
                "reference_capture_status": "quote_unavailable",
                "reference_capture_error": f"{type(exc).__name__}: {exc}",
            }

        bid = _safe_float(_quote_attr(quote, "bid_price", "bid", "bp", "bidprice"))
        ask = _safe_float(_quote_attr(quote, "ask_price", "ask", "ap", "askprice"))
        bid_size = _safe_float(_quote_attr(quote, "bid_size", "bs", "bidsize"))
        ask_size = _safe_float(_quote_attr(quote, "ask_size", "as", "asksize"))
        quote_ts = _quote_attr(quote, "timestamp", "t", "quote_timestamp")
        mid = (bid + ask) / 2.0 if bid and ask and bid > 0 and ask > 0 else None
        spread_pct = ((ask - bid) / mid * 100.0) if mid and ask is not None and bid is not None else None
        return {
            "reference_capture_status": "captured" if mid is not None else "quote_missing_bid_ask",
            "reference_price": round(mid, 6) if mid is not None else None,
            "reference_price_source": "quote_mid" if mid is not None else "quote_unavailable",
            "bid": bid,
            "ask": ask,
            "mid": round(mid, 6) if mid is not None else None,
            "spread_pct": round(spread_pct, 6) if spread_pct is not None else None,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "quote_ts": quote_ts.isoformat() if hasattr(quote_ts, "isoformat") else quote_ts,
        }


candidate_reference_service = CandidateReferenceService()
