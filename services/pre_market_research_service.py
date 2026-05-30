"""Pre-market research market-data orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from repositories.pre_market_research_repo import PreMarketResearchRepository
from services.market_data_service import market_data_service


@dataclass(frozen=True)
class PreMarketResearchConfig:
    fetch_daily_bars: bool
    fetch_minute_bars: bool
    skip_minute_if_daily_fails: bool
    daily_lookback_days: int
    minute_lookback_hours: float


class PreMarketResearchService:
    def __init__(
        self,
        *,
        repository: PreMarketResearchRepository,
        market_data,
        config: PreMarketResearchConfig,
        pct_change,
        unique_price_levels,
        logger: logging.Logger | None = None,
    ):
        self.repository = repository
        self.market_data = market_data
        self.config = config
        self.pct_change = pct_change
        self.unique_price_levels = unique_price_levels
        self.logger = logger or logging.getLogger(__name__)

    def get_recent_bars(self, symbol: str) -> dict[str, Any]:
        """Return lightweight recent data from Alpaca IEX feed."""
        out = {
            "symbol": symbol,
            "daily_pct": None,
            "intraday_pct": None,
            "momentum_30m_pct": None,
            "last_price": None,
            "support_levels": [],
            "resistance_levels": [],
            "bar_count_1m": 0,
            "error": None,
        }

        now = datetime.now(timezone.utc)
        daily_failed = False

        if self.config.fetch_daily_bars:
            try:
                daily_start = (
                    now - timedelta(days=self.config.daily_lookback_days)
                ).isoformat()
                daily_bars = self.market_data.get_bars_with_fallback(
                    symbol,
                    "1Day",
                    start=daily_start,
                    feed="iex",
                )
                if len(daily_bars) >= 2:
                    prev = daily_bars[-2]
                    last = daily_bars[-1]
                    out["daily_pct"] = self.pct_change(float(prev.c), float(last.c))
                    out["last_price"] = float(last.c)
                elif len(daily_bars) == 1:
                    out["last_price"] = float(daily_bars[-1].c)

                recent_daily = daily_bars[-5:]
                daily_supports = sorted((float(b.l) for b in recent_daily), reverse=True)
                daily_resistances = sorted((float(b.h) for b in recent_daily))
                out["support_levels"] = self.unique_price_levels(daily_supports)
                out["resistance_levels"] = self.unique_price_levels(daily_resistances)
            except Exception as e:
                daily_failed = True
                out["error"] = f"daily bars failed: {e}"

        should_fetch_minute = self.config.fetch_minute_bars and not (
            daily_failed and self.config.skip_minute_if_daily_fails
        )

        if should_fetch_minute:
            try:
                minute_start = (
                    now - timedelta(hours=self.config.minute_lookback_hours)
                ).isoformat()
                minute_bars = self.market_data.get_bars_with_fallback(
                    symbol,
                    "1Min",
                    start=minute_start,
                    feed="iex",
                )
                minute_bars = minute_bars[-120:]
                out["bar_count_1m"] = len(minute_bars)

                if len(minute_bars) >= 2:
                    first = float(minute_bars[0].c)
                    last = float(minute_bars[-1].c)
                    out["intraday_pct"] = self.pct_change(first, last)
                    out["last_price"] = last

                if len(minute_bars) >= 30:
                    first_30 = float(minute_bars[-30].c)
                    last_30 = float(minute_bars[-1].c)
                    out["momentum_30m_pct"] = self.pct_change(first_30, last_30)

                if minute_bars:
                    minute_support = min(float(b.l) for b in minute_bars)
                    minute_resistance = max(float(b.h) for b in minute_bars)
                    out["support_levels"] = self.unique_price_levels(
                        [minute_support] + out["support_levels"]
                    )
                    out["resistance_levels"] = self.unique_price_levels(
                        [minute_resistance] + out["resistance_levels"]
                    )

            except Exception as e:
                if out["error"]:
                    out["error"] += f"; minute bars failed: {e}"
                else:
                    out["error"] = f"minute bars failed: {e}"
        elif self.config.fetch_minute_bars and daily_failed:
            out["minute_fetch_skipped"] = "daily_failed"

        if out["last_price"]:
            last_price = float(out["last_price"])
            supports = [level for level in out["support_levels"] if level <= last_price]
            resistances = [
                level for level in out["resistance_levels"] if level >= last_price
            ]
            out["support_levels"] = self.unique_price_levels(
                supports + [last_price * 0.99]
            )
            out["resistance_levels"] = self.unique_price_levels(
                resistances + [last_price * 1.01]
            )
            if not out["support_levels"]:
                out["support_levels"] = self.unique_price_levels([last_price * 0.99])
            if not out["resistance_levels"]:
                out["resistance_levels"] = self.unique_price_levels([last_price * 1.01])

        return out

    def load_event_enrichment(self, market_date: str) -> dict:
        return self.repository.event_enrichment(market_date)

    def latest_session_momentum(self, symbol: str) -> dict:
        return self.repository.latest_session_momentum(symbol)

    def get_latest_prediction(self, symbol: str, market_date: str) -> dict:
        return self.repository.latest_prediction(symbol, market_date)

    def get_prior_session_context(self, symbol: str, market_date: str) -> dict:
        return self.repository.prior_session_context(symbol, market_date)

    def get_strategy_memory_context(self, symbol: str) -> dict:
        return self.repository.strategy_memory_context(symbol)


def build_default_pre_market_research_service(
    *,
    config: PreMarketResearchConfig,
    pct_change,
    unique_price_levels,
    logger: logging.Logger | None = None,
) -> PreMarketResearchService:
    return PreMarketResearchService(
        repository=PreMarketResearchRepository(),
        market_data=market_data_service,
        config=config,
        pct_change=pct_change,
        unique_price_levels=unique_price_levels,
        logger=logger,
    )
