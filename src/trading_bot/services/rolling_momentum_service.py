"""Rolling multi-day momentum context service."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import pytz
from market_time import now_et
from services.market_data_service import MarketDataService, market_data_service

ET = pytz.timezone("America/New_York")
LOOKBACK_CALENDAR_DAYS = 10
DATA_FEED = "iex"


def pct_change(new, old):
    try:
        new = float(new)
        old = float(old)
        if old <= 0:
            return None
        return (new - old) / old * 100.0
    except Exception:
        return None


def safe_round(value, digits=3):
    if value is None:
        return None
    try:
        if math.isnan(value) or math.isinf(value):
            return None
        return round(float(value), digits)
    except Exception:
        return None


def as_et(dt):
    """Convert Alpaca bar timestamp to timezone-aware Eastern time."""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET)


def _bar_value(bar: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(bar, name):
            return getattr(bar, name)
    if isinstance(bar, dict):
        for name in names:
            if name in bar:
                return bar[name]
    return default


def _bar_timestamp(bar: Any) -> Any:
    return _bar_value(bar, "t", "timestamp", "time", default=None)


def session_bucket(ts_et):
    """Return premarket / regular / postmarket / closed for a timestamp in ET."""
    minutes = ts_et.hour * 60 + ts_et.minute

    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "premarket"
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "regular"
    if 16 * 60 <= minutes < 20 * 60:
        return "postmarket"
    return "closed"


def summarize_day(day_bars):
    """Summarize one calendar date's premarket/regular/postmarket bars."""
    by_bucket = defaultdict(list)
    for b in day_bars:
        by_bucket[b["bucket"]].append(b)

    def summarize_bucket(items):
        if not items:
            return None
        return {
            "open": items[0]["open"],
            "high": max(x["high"] for x in items),
            "low": min(x["low"] for x in items),
            "close": items[-1]["close"],
            "bar_count": len(items),
            "volume": sum(x["volume"] for x in items),
        }

    pre = summarize_bucket(by_bucket["premarket"])
    reg = summarize_bucket(by_bucket["regular"])
    post = summarize_bucket(by_bucket["postmarket"])

    day = {
        "premarket": pre,
        "regular": reg,
        "postmarket": post,
    }

    day["regular_return_pct"] = safe_round(pct_change(reg["close"], reg["open"])) if reg else None
    day["premarket_to_regular_open_gap_pct"] = (
        safe_round(pct_change(reg["open"], pre["close"])) if pre and reg else None
    )
    day["postmarket_return_pct"] = (
        safe_round(pct_change(post["close"], reg["close"])) if post and reg else None
    )

    return day


def classify_context(metrics):
    score = 0
    reasons = []

    five_day = metrics.get("five_day_return_pct")
    prior_day = metrics.get("prior_day_return_pct")
    overnight_gap = metrics.get("overnight_gap_pct")
    premarket = metrics.get("premarket_return_pct")
    current_session = metrics.get("current_session_return_pct")
    current_vs_prior = metrics.get("current_price_vs_prior_close_pct")
    after_hours = metrics.get("prior_postmarket_return_pct")
    extension_from_base = metrics.get("extension_from_recent_base_pct")

    if five_day is not None:
        if five_day > 2.0:
            score += 2
            reasons.append("5d_positive")
        elif five_day < -2.0:
            score -= 2
            reasons.append("5d_negative")

    if prior_day is not None:
        if prior_day > 0.5:
            score += 1
            reasons.append("prior_day_positive")
        elif prior_day < -0.5:
            score -= 1
            reasons.append("prior_day_negative")

    if premarket is not None:
        if premarket > 0.3:
            score += 1
            reasons.append("premarket_positive")
        elif premarket < -0.3:
            score -= 1
            reasons.append("premarket_negative")

    if current_session is not None:
        if current_session > 0.3:
            score += 1
            reasons.append("session_positive")
        elif current_session < -0.3:
            score -= 1
            reasons.append("session_negative")

    if current_vs_prior is not None:
        if current_vs_prior > 0.25:
            score += 1
            reasons.append("above_prior_close")
        elif current_vs_prior < -0.25:
            score -= 1
            reasons.append("below_prior_close")

    special = []

    if (
        five_day is not None and five_day > 4 and overnight_gap is not None and overnight_gap > 1
    ) or (five_day is not None and five_day > 4.0 and prior_day is not None and prior_day > 2.0):
        special.append("gap_up_chase_risk")

    if extension_from_base is not None and extension_from_base > 3.5:
        special.append("extended_above_recent_base")

    if (
        five_day is not None
        and five_day > 2
        and current_session is not None
        and current_session < -0.3
    ):
        special.append("pullback_in_uptrend")

    if five_day is not None and five_day < -2 and premarket is not None and premarket > 0.5:
        special.append("premarket_reversal_attempt")

    if after_hours is not None and after_hours < -0.5:
        special.append("after_hours_warning")

    if premarket is not None and prior_day is not None:
        if prior_day > 0.5 and premarket > 0.3:
            special.append("premarket_confirmation")
        elif prior_day > 0.5 and premarket < -0.3:
            special.append("overnight_contradiction")

    if score >= 4:
        label = "strong_bullish_continuation"
    elif score >= 2:
        label = "bullish_continuation"
    elif score >= 0:
        label = "mixed_or_neutral"
    elif score > -4:
        label = "bearish_pressure"
    else:
        label = "bearish_continuation"

    return {
        "trend_context": label,
        "continuation_score": score,
        "reasons": reasons,
        "special_labels": special,
    }


class RollingMomentumService:
    def __init__(
        self,
        market_data: MarketDataService = market_data_service,
        lookback_calendar_days: int = LOOKBACK_CALENDAR_DAYS,
        data_feed: str = DATA_FEED,
    ):
        self.market_data = market_data
        self.lookback_calendar_days = lookback_calendar_days
        self.data_feed = data_feed

    def fetch_minute_bars(self, symbol: str) -> list[dict[str, Any]]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=self.lookback_calendar_days)

        bars = self.market_data.get_bars_with_fallback(
            symbol,
            "1Min",
            start=start.isoformat(),
            end=end.isoformat(),
            feed=self.data_feed,
        )

        out = []
        for b in bars:
            raw_ts = _bar_timestamp(b)
            if raw_ts is None:
                raise AttributeError("bar object has no timestamp/t field")
            ts = as_et(raw_ts)
            out.append(
                {
                    "ts": ts,
                    "date": ts.date().isoformat(),
                    "bucket": session_bucket(ts),
                    "open": float(_bar_value(b, "o", "open", default=0) or 0),
                    "high": float(_bar_value(b, "h", "high", default=0) or 0),
                    "low": float(_bar_value(b, "l", "low", default=0) or 0),
                    "close": float(_bar_value(b, "c", "close", default=0) or 0),
                    "volume": float(_bar_value(b, "v", "volume", default=0) or 0),
                }
            )

        out.sort(key=lambda x: x["ts"])
        return out

    def build_symbol_context(self, symbol: str) -> dict[str, Any]:
        try:
            bars = self.fetch_minute_bars(symbol)
        except Exception as exc:
            return {
                "symbol": symbol,
                "error": f"bar_fetch_failed: {exc}",
                "trend_context": "unknown",
                "continuation_score": 0,
            }

        if not bars:
            return {
                "symbol": symbol,
                "error": "no_bars_returned",
                "trend_context": "unknown",
                "continuation_score": 0,
            }

        bars_by_date = defaultdict(list)
        for bar in bars:
            bars_by_date[bar["date"]].append(bar)

        summaries = {day: summarize_day(day_bars) for day, day_bars in sorted(bars_by_date.items())}

        market_days = [
            day
            for day, summary in summaries.items()
            if summary.get("regular") and summary["regular"].get("bar_count", 0) > 0
        ]

        today = now_et().date().isoformat()
        today_summary = summaries.get(today)

        prior_market_days = [day for day in market_days if day < today]
        last_5_market_days = prior_market_days[-5:]
        prior_day = prior_market_days[-1] if prior_market_days else None

        prior_close = None
        prior_day_return = None
        prior_postmarket_return = None

        if prior_day:
            prior_reg = summaries[prior_day].get("regular")
            if prior_reg:
                prior_close = prior_reg["close"]
                prior_day_return = pct_change(prior_reg["close"], prior_reg["open"])
            prior_postmarket_return = summaries[prior_day].get("postmarket_return_pct")

        five_day_return = None
        if len(last_5_market_days) >= 2:
            first_day = last_5_market_days[0]
            last_day = last_5_market_days[-1]
            first_open = summaries[first_day]["regular"]["open"]
            last_close = summaries[last_day]["regular"]["close"]
            five_day_return = pct_change(last_close, first_open)

        extension_from_recent_base = None
        extension_from_recent_base_days = None
        recent_base_days = prior_market_days[-3:]
        recent_regular_closes = []
        for day in recent_base_days:
            reg = summaries[day].get("regular")
            if reg and reg.get("close"):
                recent_regular_closes.append(float(reg["close"]))

        latest_bar = bars[-1]
        latest_price = latest_bar["close"]
        if recent_regular_closes:
            recent_base = min(recent_regular_closes)
            extension_from_recent_base = pct_change(latest_price, recent_base)
            extension_from_recent_base_days = sum(
                1 for close in recent_regular_closes if latest_price > close
            )

        today_pre = today_summary.get("premarket") if today_summary else None
        today_reg = today_summary.get("regular") if today_summary else None
        today_post = today_summary.get("postmarket") if today_summary else None

        premarket_return = (
            pct_change(today_pre["close"], prior_close) if prior_close and today_pre else None
        )

        overnight_gap = None
        if prior_close and today_reg:
            overnight_gap = pct_change(today_reg["open"], prior_close)
        elif prior_close and today_pre:
            overnight_gap = pct_change(today_pre["close"], prior_close)

        current_session_return = pct_change(latest_price, today_reg["open"]) if today_reg else None
        current_vs_prior_close = pct_change(latest_price, prior_close) if prior_close else None

        metrics = {
            "five_day_return_pct": safe_round(five_day_return),
            "prior_day_return_pct": safe_round(prior_day_return),
            "prior_postmarket_return_pct": safe_round(prior_postmarket_return),
            "overnight_gap_pct": safe_round(overnight_gap),
            "premarket_return_pct": safe_round(premarket_return),
            "current_session_return_pct": safe_round(current_session_return),
            "current_price_vs_prior_close_pct": safe_round(current_vs_prior_close),
            "extension_from_recent_base_pct": safe_round(extension_from_recent_base),
            "extension_from_recent_base_days": extension_from_recent_base_days,
        }

        classification = classify_context(metrics)

        return {
            "symbol": symbol,
            "generated_at": datetime.now().isoformat(),
            "latest_price": safe_round(latest_price, 4),
            "latest_bar_time_et": latest_bar["ts"].isoformat(),
            "data_feed": self.data_feed,
            "lookback_calendar_days": self.lookback_calendar_days,
            "market_days_found": len(market_days),
            "last_5_market_days": last_5_market_days,
            "prior_market_day": prior_day,
            "prior_close": safe_round(prior_close, 4),
            "today": today,
            "today_premarket": today_pre,
            "today_regular": today_reg,
            "today_postmarket": today_post,
            **metrics,
            **classification,
        }
