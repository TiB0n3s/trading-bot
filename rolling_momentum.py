#!/usr/bin/env python3
"""
Rolling multi-day momentum context — observe-only.

Builds rolling_momentum.json for all approved symbols using recent Alpaca bars.

Purpose:
- Add continuity from prior sessions into today's session logic.
- Track 5-market-day trend context.
- Track premarket / regular / postmarket movement.
- Stay observe-only: this script does not place orders and does not block trades.

Output:
  rolling_momentum.json
"""

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytz

from broker import api
from symbols_config import APPROVED_SYMBOLS_LIST
from market_time import now_et

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = BASE_DIR / "rolling_momentum.json"

ET = pytz.timezone("America/New_York")

# Pull enough calendar days to usually cover 5 market days plus today,
# including weekends/holidays buffer.
LOOKBACK_CALENDAR_DAYS = 10

# Use IEX feed because the paper account has historically accepted it reliably.
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
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET)


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


def fetch_minute_bars(symbol):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_CALENDAR_DAYS)

    bars = list(
        api.get_bars(
            symbol,
            "1Min",
            start=start.isoformat(),
            end=end.isoformat(),
            feed=DATA_FEED,
        )
    )

    out = []
    for b in bars:
        ts = as_et(b.t)
        out.append(
            {
                "ts": ts,
                "date": ts.date().isoformat(),
                "bucket": session_bucket(ts),
                "open": float(b.o),
                "high": float(b.h),
                "low": float(b.l),
                "close": float(b.c),
                "volume": float(getattr(b, "v", 0) or 0),
            }
        )

    out.sort(key=lambda x: x["ts"])
    return out


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

    if reg:
        day["regular_return_pct"] = safe_round(pct_change(reg["close"], reg["open"]))
    else:
        day["regular_return_pct"] = None

    if pre and reg:
        day["premarket_to_regular_open_gap_pct"] = safe_round(
            pct_change(reg["open"], pre["close"])
        )
    else:
        day["premarket_to_regular_open_gap_pct"] = None

    if post and reg:
        day["postmarket_return_pct"] = safe_round(pct_change(post["close"], reg["close"]))
    else:
        day["postmarket_return_pct"] = None

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
        (five_day is not None and five_day > 4 and overnight_gap is not None and overnight_gap > 1)
        or (
            five_day is not None
            and five_day > 4.0
            and prior_day is not None
            and prior_day > 2.0
        )
    ):
        special.append("gap_up_chase_risk")

    if extension_from_base is not None and extension_from_base > 3.5:
        special.append("extended_above_recent_base")

    if five_day is not None and five_day > 2 and current_session is not None and current_session < -0.3:
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


def build_symbol_context(symbol):
    try:
        bars = fetch_minute_bars(symbol)
    except Exception as e:
        return {
            "symbol": symbol,
            "error": f"bar_fetch_failed: {e}",
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
    for b in bars:
        bars_by_date[b["date"]].append(b)

    summaries = {
        d: summarize_day(day_bars)
        for d, day_bars in sorted(bars_by_date.items())
    }

    # Market days are days with regular-session bars.
    market_days = [
        d for d, s in summaries.items()
        if s.get("regular") and s["regular"].get("bar_count", 0) > 0
    ]

    today = now_et().date().isoformat()
    today_summary = summaries.get(today)

    prior_market_days = [d for d in market_days if d < today]
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
    for d in recent_base_days:
        reg = summaries[d].get("regular")
        if reg and reg.get("close"):
            recent_regular_closes.append(float(reg["close"]))

    latest_bar = bars[-1]
    latest_price = latest_bar["close"]
    if recent_regular_closes:
        recent_base = min(recent_regular_closes)
        extension_from_recent_base = pct_change(latest_price, recent_base)
        extension_from_recent_base_days = sum(1 for close in recent_regular_closes if latest_price > close)

    today_pre = today_summary.get("premarket") if today_summary else None
    today_reg = today_summary.get("regular") if today_summary else None
    today_post = today_summary.get("postmarket") if today_summary else None

    premarket_return = None
    if prior_close and today_pre:
        premarket_return = pct_change(today_pre["close"], prior_close)

    overnight_gap = None
    if prior_close and today_reg:
        overnight_gap = pct_change(today_reg["open"], prior_close)
    elif prior_close and today_pre:
        overnight_gap = pct_change(today_pre["close"], prior_close)

    current_session_return = None
    if today_reg:
        current_session_return = pct_change(latest_price, today_reg["open"])

    current_vs_prior_close = None
    if prior_close:
        current_vs_prior_close = pct_change(latest_price, prior_close)

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
        "data_feed": DATA_FEED,
        "lookback_calendar_days": LOOKBACK_CALENDAR_DAYS,
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


def main():
    started = datetime.now()
    results = {}

    for sym in APPROVED_SYMBOLS_LIST:
        print(f"Processing {sym}...")
        results[sym] = build_symbol_context(sym)

    output = {
        "generated_at": datetime.now().isoformat(),
        "market_time_et": now_et().isoformat(),
        "source": "rolling_momentum.py",
        "mode": "observe_only",
        "symbols_count": len(APPROVED_SYMBOLS_LIST),
        "symbols": results,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    elapsed = (datetime.now() - started).total_seconds()

    print()
    print("=" * 96)
    print("  Rolling Momentum Context — Observe Only")
    print("=" * 96)
    print(f"  Output  : {OUTPUT_FILE}")
    print(f"  Symbols : {len(results)}")
    print(f"  Elapsed : {elapsed:.1f}s")
    print()
    print(f"{'Symbol':<7} {'Context':<32} {'Score':>5} {'5d%':>8} {'Pre%':>8} {'Gap%':>8} {'Sess%':>8} {'Special'}")
    print(f"{'-'*7} {'-'*32} {'-'*5} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*30}")

    for sym in APPROVED_SYMBOLS_LIST:
        r = results.get(sym, {})
        print(
            f"{sym:<7} "
            f"{str(r.get('trend_context', 'unknown')):<32} "
            f"{str(r.get('continuation_score', 0)):>5} "
            f"{str(r.get('five_day_return_pct')):>8} "
            f"{str(r.get('premarket_return_pct')):>8} "
            f"{str(r.get('overnight_gap_pct')):>8} "
            f"{str(r.get('current_session_return_pct')):>8} "
            f"{','.join(r.get('special_labels', []) or [])[:30]}"
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
