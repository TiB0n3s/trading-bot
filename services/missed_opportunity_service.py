"""Missed opportunity analysis service for rejected BUY signals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytz

from repositories.missed_opportunity_repo import MissedOpportunityRepository
from services.market_data_service import market_data_service

ET = pytz.timezone("America/New_York")


def parse_ts(ts):
    if not ts:
        return None

    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = ET.localize(dt)

    return dt.astimezone(timezone.utc)


def category(reason):
    if not reason:
        return "unknown"
    if ":" in reason:
        return reason.split(":", 1)[0].strip()
    return "uncategorized"


def pct_change(start_price, end_price):
    if not start_price or not end_price or start_price <= 0:
        return None
    return (end_price - start_price) / start_price * 100.0


def bar_at_or_after(bars, target_ts):
    for bar in bars:
        if bar["timestamp"] >= target_ts:
            return bar
    return None


class MissedOpportunityService:
    def __init__(
        self,
        *,
        repository: MissedOpportunityRepository,
        market_data=market_data_service,
    ):
        self.repository = repository
        self.market_data = market_data

    def load_rejections(
        self,
        target_date,
        symbol=None,
        category_filter=None,
        limit=80,
    ):
        return self.repository.load_rejections(
            target_date,
            symbol=symbol,
            category_filter=category_filter,
            limit=limit,
        )

    def fetch_forward_bars(self, symbol, ts_utc, minutes=75):
        start = ts_utc.isoformat()
        end = (ts_utc + timedelta(minutes=minutes + 5)).isoformat()

        bars = self.market_data.get_bars_with_fallback(
            symbol,
            "1Min",
            start=start,
            end=end,
            feed="iex",
        )
        out = []

        for bar in bars:
            bar_time = bar.t
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            else:
                bar_time = bar_time.astimezone(timezone.utc)

            out.append(
                {
                    "timestamp": bar_time,
                    "open": float(bar.o),
                    "high": float(bar.h),
                    "low": float(bar.l),
                    "close": float(bar.c),
                }
            )

        return out

    def analyze_row(self, row):
        symbol = row["symbol"]
        signal_price = float(row["signal_price"] or 0)
        ts_utc = parse_ts(row["timestamp"])

        base = {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "symbol": symbol,
            "signal_price": signal_price,
            "category": category(row["rejection_reason"]),
            "reason": row["rejection_reason"],
            "market_bias": row["market_bias"],
            "market_bias_effective": row["market_bias_effective"],
            "trend_direction": row["trend_direction"],
            "trend_strength": row["trend_strength"],
            "momentum_direction": row["momentum_direction"],
            "momentum_pct": row["momentum_pct"],
            "session_trend_label": row["session_trend_label"],
            "prediction_score": row["prediction_score"],
            "prediction_decision": row["prediction_decision"],
            "setup_label": row["setup_label"],
            "setup_policy_action": row["setup_policy_action"],
            "buy_opportunity_score": row["buy_opportunity_score"],
            "buy_opportunity_recommendation": row["buy_opportunity_recommendation"],
            "error": None,
        }

        if not symbol or signal_price <= 0 or not ts_utc:
            base["error"] = "invalid symbol, signal_price, or timestamp"
            return base

        try:
            bars = self.fetch_forward_bars(symbol, ts_utc, minutes=75)
        except Exception as e:
            base["error"] = f"bar fetch failed: {e}"
            return base

        if not bars:
            base["error"] = "no forward bars returned"
            return base

        for mins in (15, 30, 60):
            bar = bar_at_or_after(bars, ts_utc + timedelta(minutes=mins))
            base[f"return_{mins}m_pct"] = (
                round(pct_change(signal_price, bar["close"]), 3)
                if bar
                else None
            )

        highs = [bar["high"] for bar in bars]
        lows = [bar["low"] for bar in bars]

        mfe = pct_change(signal_price, max(highs)) if highs else None
        mae = pct_change(signal_price, min(lows)) if lows else None

        base["mfe_75m_pct"] = round(mfe, 3) if mfe is not None else None
        base["mae_75m_pct"] = round(mae, 3) if mae is not None else None

        ret_30 = base.get("return_30m_pct")

        if mfe is not None and mfe >= 0.75 and ret_30 is not None and ret_30 > 0.25:
            base["missed_classification"] = "missed_good_trade"
        elif mae is not None and mae <= -0.50 and (ret_30 is None or ret_30 <= 0):
            base["missed_classification"] = "good_rejection"
        else:
            base["missed_classification"] = "mixed_or_unclear"

        return base

    def analyze_rejections(
        self,
        *,
        target_date,
        symbol=None,
        category_filter=None,
        limit=80,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows = self.load_rejections(
            target_date,
            symbol=symbol,
            category_filter=category_filter,
            limit=limit,
        )
        return rows, [self.analyze_row(row) for row in rows]


def build_default_missed_opportunity_service(db_path=None) -> MissedOpportunityService:
    repository = (
        MissedOpportunityRepository(db_path=db_path)
        if db_path is not None
        else MissedOpportunityRepository()
    )
    return MissedOpportunityService(repository=repository)
