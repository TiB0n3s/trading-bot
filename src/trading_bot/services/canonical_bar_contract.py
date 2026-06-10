"""Shared 1-minute bar contract for live, label, and ML feature paths."""

from __future__ import annotations

from typing import Any

CANONICAL_BAR_CONTRACT_VERSION = "canonical_1min_ohlcv_vwap_v1"
CANONICAL_BAR_TIMEFRAME = "1Min"
CANONICAL_BAR_TIMEFRAME_DB = "1m"
CANONICAL_BAR_ADJUSTMENT = "raw"
CANONICAL_BAR_INTERVAL_SEMANTICS = "inclusive_start_1min"
CANONICAL_BAR_REQUIRED_FIELDS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
)


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _row_value(row: Any, *names: str) -> Any:
    for name in names:
        if hasattr(row, "get"):
            value = row.get(name)
            if value is not None:
                return value
        if hasattr(row, name):
            value = getattr(row, name)
            if value is not None:
                return value
    return None


def _timestamp_text(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def dataframe_to_canonical_bar_rows(
    bars_df: Any,
    *,
    symbol: str,
    feed: str | None = None,
    source: str = "alpaca",
    adjusted: bool | None = None,
) -> list[dict[str, Any]]:
    """Normalize a market-data DataFrame into the bar shape used by training.

    The historical ML rows are trained from 1-minute OHLCV/VWAP bars. Live feature
    capture and forward labeling should therefore request the same candle fields,
    even when a downstream consumer only needs close/high/low.
    """
    if bars_df is None or getattr(bars_df, "empty", True):
        return []

    symbol = str(symbol or "").strip().upper()
    if "symbol" in getattr(bars_df, "columns", []):
        bars_df = bars_df[bars_df["symbol"] == symbol]

    rows: list[dict[str, Any]] = []
    for idx, row in bars_df.iterrows():
        close = _float_or_none(_row_value(row, "close", "c"))
        vwap = _float_or_none(_row_value(row, "vwap", "vw", "VWAP"))
        rows.append(
            {
                "symbol": symbol,
                "timestamp": _timestamp_text(idx),
                "open": _float_or_none(_row_value(row, "open", "o")),
                "high": _float_or_none(_row_value(row, "high", "h")),
                "low": _float_or_none(_row_value(row, "low", "l")),
                "close": close,
                "volume": _float_or_none(_row_value(row, "volume", "v")),
                "vwap": close if vwap is None else vwap,
                "timeframe": CANONICAL_BAR_TIMEFRAME,
                "timeframe_db": CANONICAL_BAR_TIMEFRAME_DB,
                "adjustment": CANONICAL_BAR_ADJUSTMENT,
                "source": source,
                "feed": feed,
                "adjusted": adjusted,
                "trade_count": _float_or_none(_row_value(row, "trade_count", "transactions", "n")),
                "interval_start": _timestamp_text(idx),
                "interval_semantics": CANONICAL_BAR_INTERVAL_SEMANTICS,
                "contract_version": CANONICAL_BAR_CONTRACT_VERSION,
            }
        )
    return rows


def bar_contract_summary() -> dict[str, Any]:
    return {
        "contract_version": CANONICAL_BAR_CONTRACT_VERSION,
        "timeframe": CANONICAL_BAR_TIMEFRAME,
        "timeframe_db": CANONICAL_BAR_TIMEFRAME_DB,
        "adjustment": CANONICAL_BAR_ADJUSTMENT,
        "required_fields": list(CANONICAL_BAR_REQUIRED_FIELDS),
        "interval_semantics": CANONICAL_BAR_INTERVAL_SEMANTICS,
    }
