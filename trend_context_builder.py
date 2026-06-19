#!/usr/bin/env python3
"""
Historical trend context builder.

Creates one historical_trend_context row per symbol/date using Alpaca daily bars.

Learning-only:
- Does not modify trades.
- Does not place orders.
- Does not affect live bot decisions.

Usage:
  python3 trend_context_builder.py --date 2026-05-22
  python3 trend_context_builder.py --start-date 2026-05-18 --end-date 2026-05-22
  python3 trend_context_builder.py --date 2026-05-22 --symbol AAPL
"""

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST
from db import DB_PATH, get_connection

ENV_FILE = Path("/etc/trading-bot.env")


BENCHMARK_MAP = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "IWM": "IWM",
    "GLD": "GLD",

    # Mega-cap / tech / growth
    "AAPL": "QQQ",
    "MSFT": "QQQ",
    "NVDA": "QQQ",
    "ORCL": "QQQ",
    "TSLA": "QQQ",
    "META": "QQQ",
    "AMD": "QQQ",
    "GOOGL": "QQQ",
    "AVGO": "QQQ",
    "CRDO": "QQQ",
    "ASML": "QQQ",
    "NFLX": "QQQ",
    "CRM": "QQQ",

    # Industrial / defense / energy / value
    "CVX": "SPY",
    "XOM": "SPY",
    "TSCO": "SPY",
    "CAT": "SPY",
    "GEV": "SPY",
    "GE": "SPY",
    "LMT": "SPY",
    "RTX": "SPY",
    "HWM": "SPY",
    "LIN": "SPY",
    "COST": "SPY",
    "KO": "SPY",
    "V": "SPY",
    "MA": "SPY",

    # Healthcare / biotech
    "LLY": "SPY",
    "VRTX": "SPY",
    "MRNA": "SPY",
    "CRSP": "SPY",
    "ABBV": "SPY",
    "MRK": "SPY",
    "UNH": "SPY",

    # Small/speculative
    "BE": "IWM",
    "RKLB": "IWM",
}


def load_env():
    if os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY"):
        return

    if not ENV_FILE.exists():
        raise SystemExit(f"ERROR: missing Alpaca env and {ENV_FILE} not found")

    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

from broker import api  # noqa: E402


def init_table():
    with get_connection(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS historical_trend_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                market_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                benchmark_symbol TEXT,

                close_price REAL,
                benchmark_close REAL,

                trend_1d_pct REAL,
                trend_3d_pct REAL,
                trend_5d_pct REAL,
                trend_10d_pct REAL,
                trend_20d_pct REAL,

                benchmark_1d_pct REAL,
                benchmark_5d_pct REAL,
                relative_strength_1d_pct REAL,
                relative_strength_5d_pct REAL,
                relative_strength_score REAL,

                sma_5 REAL,
                sma_10 REAL,
                sma_20 REAL,
                above_sma_5 INTEGER,
                above_sma_10 INTEGER,
                above_sma_20 INTEGER,
                distance_from_sma_20_pct REAL,

                volatility_5d_pct REAL,
                avg_range_5d_pct REAL,
                gap_pct REAL,

                higher_highs_3d INTEGER,
                higher_lows_3d INTEGER,
                lower_highs_3d INTEGER,
                lower_lows_3d INTEGER,

                trend_label TEXT,
                trend_regime TEXT,
                trend_confidence TEXT,
                trend_reason TEXT,

                raw_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                UNIQUE(market_date, symbol)
            )
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_historical_trend_context_date_symbol
            ON historical_trend_context(market_date, symbol)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_historical_trend_context_symbol_date
            ON historical_trend_context(symbol, market_date)
        """)


def pct(old, new):
    try:
        old = float(old)
        new = float(new)
        if old == 0:
            return None
        return (new - old) / old * 100.0
    except Exception:
        return None


def avg(values):
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def sma(closes, n):
    if len(closes) < n:
        return None
    return avg(closes[-n:])


def get_daily_bars(symbol, target_date, lookback_days=45):
    end = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
    start = (date.fromisoformat(target_date) - timedelta(days=lookback_days)).isoformat()

    bars = list(api.get_bars(symbol, "1Day", start=start, end=end, feed="iex"))

    out = []
    for b in bars:
        # Alpaca bar timestamp may be datetime-like.
        ts = getattr(b, "t", None)
        day = ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10]

        if day <= target_date:
            out.append({
                "date": day,
                "open": float(b.o),
                "high": float(b.h),
                "low": float(b.l),
                "close": float(b.c),
                "volume": float(getattr(b, "v", 0) or 0),
            })

    out.sort(key=lambda x: x["date"])
    return out


def n_day_pct(closes, n):
    if len(closes) <= n:
        return None
    return pct(closes[-n-1], closes[-1])


def bool_int(value):
    if value is None:
        return None
    return 1 if value else 0


def classify_trend(features):
    t5 = features.get("trend_5d_pct")
    t10 = features.get("trend_10d_pct")
    t20 = features.get("trend_20d_pct")
    rs5 = features.get("relative_strength_5d_pct")
    dist = features.get("distance_from_sma_20_pct")
    above20 = features.get("above_sma_20")
    vol = features.get("volatility_5d_pct")
    gap = features.get("gap_pct")

    reasons = []

    def gt(v, x):
        return v is not None and v > x

    def lt(v, x):
        return v is not None and v < x

    if gt(t5, 3.0) and gt(dist, 4.0):
        label = "extended_uptrend"
        regime = "bullish_extended"
        reasons.append("5d trend strong and price extended above SMA20")
    elif gt(t10, 1.0) and above20 == 1 and (rs5 is None or rs5 >= 0):
        label = "confirmed_uptrend"
        regime = "bullish"
        reasons.append("10d trend positive, above SMA20, relative strength non-negative")
    elif gt(t10, 0.5) and lt(features.get("trend_1d_pct"), 0) and above20 == 1:
        label = "uptrend_pullback"
        regime = "bullish_pullback"
        reasons.append("positive 10d trend with negative 1d pullback while above SMA20")
    elif lt(t5, -1.0) and lt(t10, -1.0) and above20 == 0:
        label = "downtrend"
        regime = "bearish"
        reasons.append("5d/10d trend negative and below SMA20")
    elif vol is not None and vol > 4.0:
        label = "volatile_unclear"
        regime = "volatile"
        reasons.append("5d volatility elevated")
    elif gap is not None and abs(gap) > 2.0:
        label = "gap_watch"
        regime = "tactical"
        reasons.append("large daily gap")
    else:
        label = "rangebound"
        regime = "neutral"
        reasons.append("mixed or modest trend signals")

    confidence_score = 0
    for v in (t5, t10, t20, rs5, dist):
        if v is not None:
            confidence_score += 1

    if confidence_score >= 5:
        conf = "high"
    elif confidence_score >= 3:
        conf = "medium"
    else:
        conf = "low"

    return label, regime, conf, "; ".join(reasons)


def build_features(symbol, target_date, bars, benchmark_bars):
    if len(bars) < 6:
        return None

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    opens = [b["open"] for b in bars]

    latest = bars[-1]
    previous = bars[-2] if len(bars) >= 2 else None

    benchmark_symbol = BENCHMARK_MAP.get(symbol, "SPY")
    bench_closes = [b["close"] for b in benchmark_bars] if benchmark_bars else []

    close = closes[-1]
    bench_close = bench_closes[-1] if bench_closes else None

    trend_1d = pct(closes[-2], closes[-1]) if len(closes) >= 2 else None
    trend_3d = n_day_pct(closes, 3)
    trend_5d = n_day_pct(closes, 5)
    trend_10d = n_day_pct(closes, 10)
    trend_20d = n_day_pct(closes, 20)

    bench_1d = pct(bench_closes[-2], bench_closes[-1]) if len(bench_closes) >= 2 else None
    bench_5d = n_day_pct(bench_closes, 5) if bench_closes else None

    rs1 = None if trend_1d is None or bench_1d is None else trend_1d - bench_1d
    rs5 = None if trend_5d is None or bench_5d is None else trend_5d - bench_5d

    # Convert relative strength into rough 0-100 score.
    rs_score = 50
    if rs5 is not None:
        rs_score += max(-25, min(25, rs5 * 5))
    if rs1 is not None:
        rs_score += max(-10, min(10, rs1 * 3))
    rs_score = max(0, min(100, rs_score))

    sma5 = sma(closes, 5)
    sma10 = sma(closes, 10)
    sma20 = sma(closes, 20)

    dist20 = pct(sma20, close) if sma20 else None

    ranges = []
    for b in bars[-5:]:
        if b["close"]:
            ranges.append((b["high"] - b["low"]) / b["close"] * 100.0)

    daily_returns = []
    for i in range(max(1, len(closes) - 5), len(closes)):
        daily_returns.append(pct(closes[i - 1], closes[i]))

    mean_ret = avg(daily_returns)
    if mean_ret is not None and len(daily_returns) > 1:
        volatility = (sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)) ** 0.5
    else:
        volatility = None

    gap = pct(previous["close"], latest["open"]) if previous else None

    hh3 = None
    hl3 = None
    lh3 = None
    ll3 = None
    if len(highs) >= 4 and len(lows) >= 4:
        last_highs = highs[-3:]
        prev_highs = highs[-4:-1]
        last_lows = lows[-3:]
        prev_lows = lows[-4:-1]
        hh3 = all(a > b for a, b in zip(last_highs, prev_highs))
        hl3 = all(a > b for a, b in zip(last_lows, prev_lows))
        lh3 = all(a < b for a, b in zip(last_highs, prev_highs))
        ll3 = all(a < b for a, b in zip(last_lows, prev_lows))

    features = {
        "market_date": target_date,
        "symbol": symbol,
        "benchmark_symbol": benchmark_symbol,

        "close_price": close,
        "benchmark_close": bench_close,

        "trend_1d_pct": trend_1d,
        "trend_3d_pct": trend_3d,
        "trend_5d_pct": trend_5d,
        "trend_10d_pct": trend_10d,
        "trend_20d_pct": trend_20d,

        "benchmark_1d_pct": bench_1d,
        "benchmark_5d_pct": bench_5d,
        "relative_strength_1d_pct": rs1,
        "relative_strength_5d_pct": rs5,
        "relative_strength_score": rs_score,

        "sma_5": sma5,
        "sma_10": sma10,
        "sma_20": sma20,
        "above_sma_5": bool_int(close > sma5) if sma5 is not None else None,
        "above_sma_10": bool_int(close > sma10) if sma10 is not None else None,
        "above_sma_20": bool_int(close > sma20) if sma20 is not None else None,
        "distance_from_sma_20_pct": dist20,

        "volatility_5d_pct": volatility,
        "avg_range_5d_pct": avg(ranges),
        "gap_pct": gap,

        "higher_highs_3d": bool_int(hh3),
        "higher_lows_3d": bool_int(hl3),
        "lower_highs_3d": bool_int(lh3),
        "lower_lows_3d": bool_int(ll3),
    }

    label, regime, conf, reason = classify_trend(features)
    features["trend_label"] = label
    features["trend_regime"] = regime
    features["trend_confidence"] = conf
    features["trend_reason"] = reason
    features["raw_json"] = json.dumps({"bars": bars[-25:], "benchmark_bars": benchmark_bars[-25:] if benchmark_bars else []})

    return features


def upsert_feature(row):
    now = datetime.now().isoformat(sep=" ", timespec="seconds")

    cols = [
        "market_date", "symbol", "benchmark_symbol",
        "close_price", "benchmark_close",
        "trend_1d_pct", "trend_3d_pct", "trend_5d_pct", "trend_10d_pct", "trend_20d_pct",
        "benchmark_1d_pct", "benchmark_5d_pct",
        "relative_strength_1d_pct", "relative_strength_5d_pct", "relative_strength_score",
        "sma_5", "sma_10", "sma_20",
        "above_sma_5", "above_sma_10", "above_sma_20", "distance_from_sma_20_pct",
        "volatility_5d_pct", "avg_range_5d_pct", "gap_pct",
        "higher_highs_3d", "higher_lows_3d", "lower_highs_3d", "lower_lows_3d",
        "trend_label", "trend_regime", "trend_confidence", "trend_reason",
        "raw_json", "created_at", "updated_at",
    ]

    row = dict(row)
    row["created_at"] = now
    row["updated_at"] = now

    placeholders = ", ".join(["?"] * len(cols))
    update_cols = [c for c in cols if c not in ("market_date", "symbol", "created_at")]
    update_sql = ", ".join(f"{c}=excluded.{c}" for c in update_cols)

    with get_connection(DB_PATH) as con:
        con.execute(
            f"""
            INSERT INTO historical_trend_context ({", ".join(cols)})
            VALUES ({placeholders})
            ON CONFLICT(market_date, symbol)
            DO UPDATE SET {update_sql}
            """,
            [row.get(c) for c in cols],
        )


def date_range(start_date, end_date):
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d.isoformat()
        d += timedelta(days=1)


def build_for_date(target_date, symbols):
    init_table()

    all_needed = set(symbols)
    all_needed.update(BENCHMARK_MAP.get(s, "SPY") for s in symbols)

    bar_cache = {}
    for sym in sorted(all_needed):
        try:
            bar_cache[sym] = get_daily_bars(sym, target_date)
        except Exception as e:
            print(f"[WARN] failed bars for {sym} {target_date}: {e}")
            bar_cache[sym] = []

    built = []
    skipped = []

    for sym in symbols:
        bars = bar_cache.get(sym, [])
        bench = BENCHMARK_MAP.get(sym, "SPY")
        benchmark_bars = bar_cache.get(bench, [])

        features = build_features(sym, target_date, bars, benchmark_bars)
        if not features:
            skipped.append(sym)
            continue

        upsert_feature(features)
        built.append(features)

    return built, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--symbol", action="append")
    args = parser.parse_args()

    if not args.date and not (args.start_date and args.end_date):
        raise SystemExit("ERROR: provide --date or --start-date/--end-date")

    symbols = [s.upper() for s in args.symbol] if args.symbol else APPROVED_SYMBOLS_LIST

    invalid = sorted(set(symbols) - set(APPROVED_SYMBOLS_LIST))
    if invalid:
        raise SystemExit(f"ERROR: non-approved symbols: {invalid}")

    dates = [args.date] if args.date else list(date_range(args.start_date, args.end_date))

    total_built = 0
    total_skipped = 0

    for d in dates:
        built, skipped = build_for_date(d, symbols)
        total_built += len(built)
        total_skipped += len(skipped)

        print()
        print(f"=== Trend context built for {d} ===")
        print(f"  Built   : {len(built)}")
        print(f"  Skipped : {len(skipped)}")
        if skipped:
            print(f"  Missing : {', '.join(skipped[:20])}")

        print()
        print(f"  {'Symbol':<7} {'Trend':<20} {'Regime':<18} {'Conf':<7} {'1d%':>8} {'5d%':>8} {'10d%':>8} {'RS':>6} {'Dist20':>8}")
        print(f"  {'-'*7} {'-'*20} {'-'*18} {'-'*7} {'-'*8} {'-'*8} {'-'*8} {'-'*6} {'-'*8}")

        for r in built[:50]:
            def f(v):
                return "-" if v is None else f"{float(v):+.2f}"

            print(
                f"  {r['symbol']:<7} "
                f"{r['trend_label']:<20} "
                f"{r['trend_regime']:<18} "
                f"{r['trend_confidence']:<7} "
                f"{f(r['trend_1d_pct']):>8} "
                f"{f(r['trend_5d_pct']):>8} "
                f"{f(r['trend_10d_pct']):>8} "
                f"{float(r['relative_strength_score']):>6.0f} "
                f"{f(r['distance_from_sma_20_pct']):>8}"
            )

    print()
    print("=== Trend context complete ===")
    print(f"  Dates   : {len(dates)}")
    print(f"  Built   : {total_built}")
    print(f"  Skipped : {total_skipped}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
