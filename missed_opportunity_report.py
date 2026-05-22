#!/usr/bin/env python3
"""
Missed opportunity report.

Read-only analysis of rejected BUY signals:
- Looks at rejected BUY rows in trades.db
- Fetches later 1-minute bars from Alpaca
- Estimates forward return at 15/30/60 minutes
- Estimates max favorable/adverse excursion after rejection
- Helps determine whether filters are too strict or protective

This does not place, cancel, or modify orders.
"""

import argparse
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytz

from broker import api
from db import DB_PATH, get_connection


ET = pytz.timezone("America/New_York")


def parse_ts(ts):
    if not ts:
        return None

    # trades.db timestamps are generally local naive strings.
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


def pct_change(from_price, to_price):
    if not from_price or not to_price or from_price <= 0:
        return None
    return (to_price - from_price) / from_price * 100.0


def fetch_forward_bars(symbol, ts_utc, minutes=75):
    """
    Fetch 1-minute IEX bars after a rejected signal.

    Paper accounts generally support IEX feed better than SIP.
    """
    start = ts_utc.isoformat()
    end = (ts_utc + timedelta(minutes=minutes + 5)).isoformat()

    bars = list(api.get_bars(symbol, "1Min", start=start, end=end, feed="iex"))
    out = []

    for b in bars:
        try:
            bt = b.t
            if bt.tzinfo is None:
                bt = bt.replace(tzinfo=timezone.utc)
            else:
                bt = bt.astimezone(timezone.utc)

            out.append({
                "timestamp": bt,
                "open": float(b.o),
                "high": float(b.h),
                "low": float(b.l),
                "close": float(b.c),
            })
        except Exception:
            continue

    return out


def bar_at_or_after(bars, target_ts):
    for b in bars:
        if b["timestamp"] >= target_ts:
            return b
    return None


def analyze_rejection(row):
    symbol = row["symbol"]
    signal_price = float(row["signal_price"] or 0)
    ts_utc = parse_ts(row["timestamp"])

    if not symbol or signal_price <= 0 or not ts_utc:
        return None

    try:
        bars = fetch_forward_bars(symbol, ts_utc, minutes=75)
    except Exception as e:
        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "symbol": symbol,
            "category": category(row["rejection_reason"]),
            "reason": row["rejection_reason"],
            "error": str(e),
        }

    if not bars:
        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "symbol": symbol,
            "category": category(row["rejection_reason"]),
            "reason": row["rejection_reason"],
            "error": "no forward bars returned",
        }

    result = {
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

    for mins in (15, 30, 60):
        target = ts_utc + timedelta(minutes=mins)
        b = bar_at_or_after(bars, target)
        result[f"return_{mins}m_pct"] = (
            round(pct_change(signal_price, b["close"]), 3)
            if b else None
        )

    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    mfe_pct = pct_change(signal_price, max(highs)) if highs else None
    mae_pct = pct_change(signal_price, min(lows)) if lows else None

    result["mfe_75m_pct"] = round(mfe_pct, 3) if mfe_pct is not None else None
    result["mae_75m_pct"] = round(mae_pct, 3) if mae_pct is not None else None

    # Simple classification:
    # - missed_good: price moved meaningfully favorable after rejection
    # - good_reject: price moved against or never offered much upside
    # - mixed: ambiguous
    ret_30 = result.get("return_30m_pct")
    mfe = result.get("mfe_75m_pct")
    mae = result.get("mae_75m_pct")

    if mfe is not None and mfe >= 0.75 and (ret_30 is not None and ret_30 > 0.25):
        result["missed_classification"] = "missed_good_trade"
    elif mae is not None and mae <= -0.50 and (ret_30 is None or ret_30 <= 0):
        result["missed_classification"] = "good_rejection"
    else:
        result["missed_classification"] = "mixed_or_unclear"

    return result


def load_rejections(target_date, symbol=None, category_filter=None, limit=100):
    params = [f"{target_date}%"]
    extra = ""

    if symbol:
        extra += " AND symbol = ?"
        params.append(symbol.upper())

    if category_filter:
        extra += " AND rejection_reason LIKE ?"
        params.append(f"{category_filter}:%")

    with get_connection(DB_PATH) as con:
        rows = con.execute(f"""
            SELECT
                id,
                timestamp,
                symbol,
                action,
                signal_price,
                approved,
                rejection_reason,

                market_bias,
                market_bias_effective,
                trend_direction,
                trend_strength,
                momentum_direction,
                momentum_pct,

                session_trend_label,
                prediction_score,
                prediction_decision,
                setup_label,
                setup_policy_action,
                buy_opportunity_score,
                buy_opportunity_recommendation
            FROM trades
            WHERE approved = 0
              AND LOWER(action) = 'buy'
              AND signal_price IS NOT NULL
              AND rejection_reason IS NOT NULL
              AND timestamp LIKE ?
              {extra}
            ORDER BY id DESC
            LIMIT ?
        """, params + [limit]).fetchall()

    return rows


def summarize(results):
    valid = [r for r in results if r and not r.get("error")]

    by_category = defaultdict(list)
    by_symbol = defaultdict(list)
    by_class = defaultdict(int)

    for r in valid:
        by_category[r["category"]].append(r)
        by_symbol[r["symbol"]].append(r)
        by_class[r["missed_classification"]] += 1

    print()
    print("── Summary ───────────────────────────────────────────")
    print(f"Analyzed rows      : {len(results)}")
    print(f"Rows with bar data : {len(valid)}")
    print(f"Rows with errors   : {len(results) - len(valid)}")

    if by_class:
        print()
        print("Classification:")
        for k, n in sorted(by_class.items(), key=lambda x: -x[1]):
            print(f"  {k:<22} {n}")

    print()
    print("── By rejection category ─────────────────────────────")
    if not by_category:
        print("  No valid rows.")
    else:
        print(f"  {'Category':<28} {'N':>4} {'Avg30m%':>9} {'AvgMFE%':>9} {'AvgMAE%':>9} {'MissedGood':>10}")
        print(f"  {'-'*28} {'-'*4} {'-'*9} {'-'*9} {'-'*9} {'-'*10}")

        for cat, rows in sorted(by_category.items(), key=lambda x: -len(x[1])):
            r30 = [r["return_30m_pct"] for r in rows if r.get("return_30m_pct") is not None]
            mfe = [r["mfe_75m_pct"] for r in rows if r.get("mfe_75m_pct") is not None]
            mae = [r["mae_75m_pct"] for r in rows if r.get("mae_75m_pct") is not None]
            missed = sum(1 for r in rows if r.get("missed_classification") == "missed_good_trade")

            avg30 = statistics.mean(r30) if r30 else 0.0
            avgmfe = statistics.mean(mfe) if mfe else 0.0
            avgmae = statistics.mean(mae) if mae else 0.0

            print(f"  {cat:<28} {len(rows):>4} {avg30:>9.3f} {avgmfe:>9.3f} {avgmae:>9.3f} {missed:>10}")

    print()
    print("── By symbol ─────────────────────────────────────────")
    if not by_symbol:
        print("  No valid rows.")
    else:
        print(f"  {'Symbol':<8} {'N':>4} {'Avg30m%':>9} {'AvgMFE%':>9} {'AvgMAE%':>9} {'MissedGood':>10}")
        print(f"  {'-'*8} {'-'*4} {'-'*9} {'-'*9} {'-'*9} {'-'*10}")

        for sym, rows in sorted(by_symbol.items(), key=lambda x: -len(x[1]))[:25]:
            r30 = [r["return_30m_pct"] for r in rows if r.get("return_30m_pct") is not None]
            mfe = [r["mfe_75m_pct"] for r in rows if r.get("mfe_75m_pct") is not None]
            mae = [r["mae_75m_pct"] for r in rows if r.get("mae_75m_pct") is not None]
            missed = sum(1 for r in rows if r.get("missed_classification") == "missed_good_trade")

            avg30 = statistics.mean(r30) if r30 else 0.0
            avgmfe = statistics.mean(mfe) if mfe else 0.0
            avgmae = statistics.mean(mae) if mae else 0.0

            print(f"  {sym:<8} {len(rows):>4} {avg30:>9.3f} {avgmfe:>9.3f} {avgmae:>9.3f} {missed:>10}")


def print_samples(results, limit=20):
    valid = [r for r in results if r and not r.get("error")]
    valid = sorted(
        valid,
        key=lambda r: (r.get("mfe_75m_pct") or 0),
        reverse=True,
    )

    print()
    print("── Top possible missed good trades ───────────────────")
    if not valid:
        print("  None.")
        return

    print(
        f"  {'Time':<19} {'Sym':<6} {'Cat':<22} "
        f"{'30m%':>7} {'60m%':>7} {'MFE%':>7} {'MAE%':>7} "
        f"{'Class':<18} Reason"
    )
    print(
        f"  {'-'*19} {'-'*6} {'-'*22} "
        f"{'-'*7} {'-'*7} {'-'*7} {'-'*7} "
        f"{'-'*18} {'-'*40}"
    )

    for r in valid[:limit]:
        reason = (r.get("reason") or "")[:80]
        print(
            f"  {r['timestamp']:<19} {r['symbol']:<6} {r['category']:<22} "
            f"{str(r.get('return_30m_pct')):>7} "
            f"{str(r.get('return_60m_pct')):>7} "
            f"{str(r.get('mfe_75m_pct')):>7} "
            f"{str(r.get('mae_75m_pct')):>7} "
            f"{r.get('missed_classification'):<18} {reason}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(ET).date().isoformat())
    parser.add_argument("--symbol")
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()

    print("=" * 72)
    print(f"  Missed Opportunity Report — {args.date}")
    print("=" * 72)

    rows = load_rejections(
        target_date=args.date,
        symbol=args.symbol,
        category_filter=args.category,
        limit=args.limit,
    )

    print(f"Rejected BUY rows loaded: {len(rows)}")

    results = []
    for row in rows:
        results.append(analyze_rejection(row))

    summarize(results)
    print_samples(results, limit=args.samples)

    errors = [r for r in results if r and r.get("error")]
    if errors:
        print()
        print("── Errors / skipped rows ─────────────────────────────")
        for r in errors[:10]:
            print(f"  id={r.get('id')} {r.get('symbol')} {r.get('category')}: {r.get('error')}")


if __name__ == "__main__":
    main()
