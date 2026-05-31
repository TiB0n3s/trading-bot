"""Market-data helpers for strong-day participation analytics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytz

ET = pytz.timezone("America/New_York")


class StrongDayParticipationService:
    def __init__(self, market_data_service: Any):
        self.market_data_service = market_data_service

    def session_window_utc(self, date_str: str):
        d = datetime.fromisoformat(date_str)
        open_et = ET.localize(datetime(d.year, d.month, d.day, 9, 30, 0))
        close_et = ET.localize(datetime(d.year, d.month, d.day, 16, 10, 0))
        return open_et.astimezone(timezone.utc), close_et.astimezone(timezone.utc)

    def fetch_session_bars(self, symbol: str, date_str: str) -> list[dict[str, Any]]:
        start_utc, end_utc = self.session_window_utc(date_str)
        bars = self.market_data_service.get_bars_with_fallback(
            symbol,
            "1Min",
            start=start_utc.isoformat(),
            end=end_utc.isoformat(),
            feed="iex",
        )
        out = []
        for bar in bars:
            bar_time = bar.t
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            else:
                bar_time = bar_time.astimezone(timezone.utc)
            out.append({
                "timestamp": bar_time,
                "open": float(bar.o),
                "high": float(bar.h),
                "low": float(bar.l),
                "close": float(bar.c),
                "volume": float(getattr(bar, "v", 0) or 0),
            })
        return out
