"""Live closed-bar ingestion for session momentum and pattern learning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import time
from typing import Any, Iterable

from services.market_data_service import market_data_service
from services.session_momentum_service import get_default_session_momentum_service


LIVE_BAR_STREAM_VERSION = "live_bar_stream_v1"
LIVE_BAR_RUNTIME_EFFECT = "observe_only_bar_learning_no_direct_order_authority"
DEFAULT_FEED = os.getenv("ALPACA_BAR_STREAM_FEED", os.getenv("MARKET_DATA_BAR_FEED", "iex"))
DEFAULT_GAP_FILL_MINUTES = int(os.getenv("LIVE_BAR_GAP_FILL_MINUTES", "90") or "90")
DEFAULT_MAX_ROLLING_BARS = int(os.getenv("LIVE_BAR_MAX_ROLLING_BARS", "390") or "390")
RECONNECT_DELAY = int(os.getenv("LIVE_BAR_STREAM_RECONNECT_DELAY_SECONDS", "30") or "30")


def _load_stock_data_stream():
    try:
        from alpaca.data.live import StockDataStream  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "alpaca-py is required for live bar streaming. Install with "
            "`./venv/bin/pip install alpaca-py`, or keep using session_momentum.py polling."
        ) from exc
    return StockDataStream


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _timestamp(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return str(value)


def _bar_attr(bar: Any, *names: str) -> Any:
    if isinstance(bar, dict):
        for name in names:
            if name in bar:
                return bar.get(name)
        return None
    for name in names:
        if hasattr(bar, name):
            return getattr(bar, name)
    return None


def normalize_live_bar(bar: Any, *, feed: str | None = None) -> dict[str, Any]:
    return {
        "symbol": str(_bar_attr(bar, "symbol", "S") or "").upper(),
        "timestamp": _timestamp(_bar_attr(bar, "timestamp", "t")),
        "open": _float(_bar_attr(bar, "open", "o")),
        "high": _float(_bar_attr(bar, "high", "h")),
        "low": _float(_bar_attr(bar, "low", "l")),
        "close": _float(_bar_attr(bar, "close", "c")),
        "volume": _float(_bar_attr(bar, "volume", "v")),
        "vwap": _float(_bar_attr(bar, "vwap", "vw")),
        "source": "alpaca_live_bar_stream",
        "feed": feed,
        "interval_semantics": "inclusive_start_live_closed_1m",
    }


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    try:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _dedupe_sort_bars(bars: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    for bar in bars:
        close = _float(bar.get("close"))
        ts = _timestamp(bar.get("timestamp"))
        if close is None or not ts:
            continue
        normalized = dict(bar)
        normalized["timestamp"] = ts
        keyed[ts] = normalized
    return sorted(keyed.values(), key=lambda row: row["timestamp"])


@dataclass
class LiveBarIngestResult:
    report_version: str
    runtime_effect: str
    symbol: str
    feed: str
    gap_fill_attempted: bool
    gap_fill_rows: int
    rolling_bars: int
    trend_label: str | None
    trend_score: int | None
    latest_price: float | None
    persisted: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "runtime_effect": self.runtime_effect,
            "symbol": self.symbol,
            "feed": self.feed,
            "gap_fill_attempted": self.gap_fill_attempted,
            "gap_fill_rows": self.gap_fill_rows,
            "rolling_bars": self.rolling_bars,
            "trend_label": self.trend_label,
            "trend_score": self.trend_score,
            "latest_price": self.latest_price,
            "persisted": self.persisted,
        }


class LiveBarStreamService:
    def __init__(
        self,
        *,
        session_momentum_service=None,
        market_data=None,
        logger: logging.Logger | None = None,
        stream_cls: Any | None = None,
        api_key: str | None = None,
        secret_key: str | None = None,
        feed: str | None = None,
        gap_fill_minutes: int = DEFAULT_GAP_FILL_MINUTES,
        max_rolling_bars: int = DEFAULT_MAX_ROLLING_BARS,
        reconnect_delay: int = RECONNECT_DELAY,
    ):
        self.session_momentum_service = (
            session_momentum_service or get_default_session_momentum_service()
        )
        self.market_data = market_data or market_data_service
        self.logger = logger or logging.getLogger(__name__)
        self.stream_cls = stream_cls
        self.api_key = api_key if api_key is not None else os.environ.get("ALPACA_API_KEY", "")
        self.secret_key = (
            secret_key if secret_key is not None else os.environ.get("ALPACA_SECRET_KEY", "")
        )
        self.feed = (feed or DEFAULT_FEED or "iex").strip().lower()
        self.gap_fill_minutes = max(1, int(gap_fill_minutes))
        self.max_rolling_bars = max(10, int(max_rolling_bars))
        self.reconnect_delay = max(1, int(reconnect_delay))
        self._bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
        self._last_bar_ts: dict[str, datetime] = {}

    def _gap_fill(self, symbol: str) -> list[dict[str, Any]]:
        try:
            rows = self.market_data.get_recent_bar_dicts(
                symbol,
                lookback_minutes=self.gap_fill_minutes,
                timeframe="1Min",
                feed=self.feed,
            )
            normalized = []
            for row in rows:
                item = dict(row)
                item["symbol"] = symbol
                normalized.append(item)
            return _dedupe_sort_bars(normalized)
        except Exception as exc:
            self.logger.warning(
                "live bar gap-fill failed for %s feed=%s: %s: %s",
                symbol,
                self.feed,
                type(exc).__name__,
                exc,
            )
            return []

    def ingest_bar(self, bar: Any) -> LiveBarIngestResult:
        normalized = normalize_live_bar(bar, feed=self.feed)
        symbol = normalized["symbol"]
        if not symbol:
            raise ValueError("live bar missing symbol")

        current_ts = _parse_ts(normalized.get("timestamp"))
        previous_ts = self._last_bar_ts.get(symbol)
        gap_fill_attempted = False
        gap_fill_rows = 0

        if symbol not in self._bars_by_symbol or (
            current_ts is not None
            and previous_ts is not None
            and current_ts - previous_ts > timedelta(minutes=2)
        ):
            gap_fill_attempted = True
            fill_rows = self._gap_fill(symbol)
            for row in fill_rows:
                row.setdefault("source", "alpaca_gap_fill_bars")
                row.setdefault("feed", self.feed)
                row.setdefault("interval_semantics", "inclusive_start_gap_fill_1m")
            gap_fill_rows = len(fill_rows)
            if fill_rows:
                self._bars_by_symbol[symbol] = fill_rows

        combined = self._bars_by_symbol.get(symbol, []) + [normalized]
        rolling = _dedupe_sort_bars(combined)[-self.max_rolling_bars :]
        self._bars_by_symbol[symbol] = rolling
        if current_ts is not None:
            self._last_bar_ts[symbol] = current_ts

        row = self.session_momentum_service.refresh_from_bars(symbol, rolling)
        self.logger.info(
            "LIVE_BAR_INGEST symbol=%s feed=%s rolling_bars=%s trend=%s/%s latest=%s",
            symbol,
            self.feed,
            len(rolling),
            row.get("trend_label"),
            row.get("trend_score"),
            row.get("latest_price"),
        )
        return LiveBarIngestResult(
            report_version=LIVE_BAR_STREAM_VERSION,
            runtime_effect=LIVE_BAR_RUNTIME_EFFECT,
            symbol=symbol,
            feed=self.feed,
            gap_fill_attempted=gap_fill_attempted,
            gap_fill_rows=gap_fill_rows,
            rolling_bars=len(rolling),
            trend_label=row.get("trend_label"),
            trend_score=row.get("trend_score"),
            latest_price=row.get("latest_price"),
            persisted=True,
        )

    async def handle_bar(self, bar: Any) -> None:
        self.ingest_bar(bar)

    def run_stream_once(self, symbols: list[str]) -> None:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("ALPACA_API_KEY or ALPACA_SECRET_KEY is not configured")
        stream_cls = self.stream_cls or _load_stock_data_stream()
        stream = stream_cls(self.api_key, self.secret_key, feed=self.feed)
        stream.subscribe_bars(self.handle_bar, *[s.upper() for s in symbols])
        self.logger.info(
            "Starting live 1-minute bar stream: symbols=%s feed=%s runtime_effect=%s",
            len(symbols),
            self.feed,
            LIVE_BAR_RUNTIME_EFFECT,
        )
        stream.run()

    def run(self, symbols: list[str]) -> None:
        if not symbols:
            raise RuntimeError("No symbols provided for live bar stream")
        while True:
            try:
                self.run_stream_once(symbols)
                self.logger.warning(
                    "Live bar stream exited unexpectedly - reconnecting in %ds",
                    self.reconnect_delay,
                )
            except KeyboardInterrupt:
                self.logger.info("Interrupted - shutting down live bar stream")
                break
            except Exception as exc:
                self.logger.error(
                    "Live bar stream error: %s - reconnecting in %ds",
                    exc,
                    self.reconnect_delay,
                )
            time.sleep(self.reconnect_delay)
