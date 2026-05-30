#!/usr/bin/env python3
"""
Excursion Report

Read-only MFE/MAE analysis for closed matched trades.

For each matched trade:
- Fetches 1-minute Alpaca IEX bars between entry and exit
- Calculates max favorable excursion (MFE)
- Calculates max adverse excursion (MAE)
- Calculates profit giveback from best available unrealized profit
- Helps determine whether losses are entry problems or exit problems

This does not place, cancel, or modify orders.
"""

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pytz

from services.market_data_service import market_data_service
from db import DB_PATH, get_connection
from policy_artifacts import atomic_write_json


ET = pytz.timezone("America/New_York")
BASE_DIR = Path(__file__).resolve().parent
EXCURSION_MEMORY_FILE = BASE_DIR / "excursion_memory.json"


def parse_ts(ts):
    if not ts:
        return None

    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = ET.localize(dt)

    return dt.astimezone(timezone.utc)


def pct_change(start_price, end_price):
    if not start_price or not end_price or start_price <= 0:
        return None
    return (end_price - start_price) / start_price * 100.0


def fetch_trade_bars(symbol, entry_ts_utc, exit_ts_utc):
    start = entry_ts_utc.isoformat()
    end = exit_ts_utc.isoformat()

    bars = market_data_service.get_bars_with_fallback(
        symbol,
        "1Min",
        start=start,
        end=end,
        feed="iex",
    )
    out = []

    for b in bars:
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

    return out


def classify_trade(row, mfe_pct, mae_pct, giveback_pct):
    pnl = float(row["realized_pnl"] or 0)

    if mfe_pct is None or mae_pct is None:
        return "insufficient_data"

    if pnl < 0 and mfe_pct < 0.25:
        return "bad_entry_never_worked"

    if pnl < 0 and mfe_pct >= 0.50:
        return "winner_became_loser"

    if pnl > 0 and giveback_pct is not None and giveback_pct >= 50:
        return "profit_giveback"

    if pnl > 0 and mfe_pct >= 0.75:
        return "good_trade"

    if mae_pct <= -1.0:
        return "large_adverse_excursion"

    return "mixed"


def analyze_trade(row):
    symbol = row["symbol"]
    entry_price = float(row["entry_price"] or 0)
    exit_price = float(row["exit_price"] or 0)
    qty = float(row["qty"] or 0)

    entry_ts = parse_ts(row["entry_timestamp"])
    exit_ts = parse_ts(row["exit_timestamp"])

    result = {
        "id": row["id"],
        "symbol": symbol,
        "entry_timestamp": row["entry_timestamp"],
        "exit_timestamp": row["exit_timestamp"],
        "holding_minutes": row["holding_minutes"],
        "qty": qty,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "realized_pnl": float(row["realized_pnl"] or 0),
        "realized_pnl_pct": float(row["realized_pnl_pct"] or 0),
        "market_bias": row["market_bias"],
        "market_bias_effective": row["market_bias_effective"],
        "trend_direction": row["trend_direction"],
        "trend_strength": row["trend_strength"],
        "session_trend_label": row["session_trend_label"],
        "prediction_decision": row["prediction_decision"],
        "setup_label": row["setup_label"],
        "setup_policy_action": row["setup_policy_action"],
        "buy_opportunity_recommendation": row["buy_opportunity_recommendation"],
        "error": None,
    }

    if not symbol or entry_price <= 0 or exit_price <= 0 or not entry_ts or not exit_ts:
        result["error"] = "invalid symbol, prices, or timestamps"
        return result

    if exit_ts <= entry_ts:
        result["error"] = "exit timestamp is not after entry timestamp"
        return result

    try:
        bars = fetch_trade_bars(symbol, entry_ts, exit_ts)
    except Exception as e:
        result["error"] = f"bar fetch failed: {e}"
        return result

    if not bars:
        result["error"] = "no bars returned for trade window"
        return result

    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    max_high = max(highs)
    min_low = min(lows)

    mfe_pct = pct_change(entry_price, max_high)
    mae_pct = pct_change(entry_price, min_low)

    mfe_dollars = (max_high - entry_price) * qty
    mae_dollars = (min_low - entry_price) * qty

    realized_pnl = float(row["realized_pnl"] or 0)

    giveback_dollars = None
    giveback_pct = None

    if mfe_dollars > 0:
        giveback_dollars = mfe_dollars - realized_pnl
        giveback_pct = giveback_dollars / mfe_dollars * 100.0

    result.update({
        "mfe_pct": round(mfe_pct, 3) if mfe_pct is not None else None,
        "mae_pct": round(mae_pct, 3) if mae_pct is not None else None,
        "mfe_dollars": round(mfe_dollars, 2),
        "mae_dollars": round(mae_dollars, 2),
        "max_high": round(max_high, 4),
        "min_low": round(min_low, 4),
        "profit_giveback_dollars": round(giveback_dollars, 2) if giveback_dollars is not None else None,
        "profit_giveback_pct": round(giveback_pct, 1) if giveback_pct is not None else None,
        "bar_count": len(bars),
    })

    result["excursion_classification"] = classify_trade(
        row,
        result["mfe_pct"],
        result["mae_pct"],
        result["profit_giveback_pct"],
    )

    return result


def load_matched_trades(target_date=None, symbol=None, limit=100):
    params = []
    extra = ""

    if target_date:
        extra += " AND exit_timestamp LIKE ?"
        params.append(f"{target_date}%")

    if symbol:
        extra += " AND symbol = ?"
        params.append(symbol.upper())

    params.append(limit)

    with get_connection(DB_PATH) as con:
        rows = con.execute(f"""
            SELECT *
            FROM matched_trades
            WHERE 1=1
              {extra}
            ORDER BY exit_timestamp DESC
            LIMIT ?
        """, params).fetchall()

    return rows


def avg(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else 0.0


def summarize(results):
    valid = [r for r in results if r and not r.get("error")]
    errors = [r for r in results if r and r.get("error")]

    by_class = defaultdict(list)
    by_symbol = defaultdict(list)
    by_setup = defaultdict(list)

    for r in valid:
        by_class[r["excursion_classification"]].append(r)
        by_symbol[r["symbol"]].append(r)
        by_setup[r.get("setup_label") or "unknown"].append(r)

    print()
    print("── Summary ───────────────────────────────────────────")
    print(f"Analyzed trades   : {len(results)}")
    print(f"Trades with bars  : {len(valid)}")
    print(f"Rows with errors  : {len(errors)}")

    if valid:
        print(f"Total realized P&L: ${sum(r['realized_pnl'] for r in valid):+.2f}")
        print(f"Avg MFE %         : {avg([r.get('mfe_pct') for r in valid]):+.3f}%")
        print(f"Avg MAE %         : {avg([r.get('mae_pct') for r in valid]):+.3f}%")
        print(f"Avg giveback %    : {avg([r.get('profit_giveback_pct') for r in valid]):+.1f}%")

    print()
    print("── Classification ────────────────────────────────────")
    if not by_class:
        print("  No valid classifications.")
    else:
        for cls, rows in sorted(by_class.items(), key=lambda x: -len(x[1])):
            pnl = sum(r["realized_pnl"] for r in rows)
            print(
                f"  {cls:<28} {len(rows):>4} "
                f"P&L=${pnl:+.2f} "
                f"AvgMFE={avg([r.get('mfe_pct') for r in rows]):+.3f}% "
                f"AvgMAE={avg([r.get('mae_pct') for r in rows]):+.3f}% "
                f"AvgGiveback={avg([r.get('profit_giveback_pct') for r in rows]):+.1f}%"
            )

    print()
    print("── By symbol ─────────────────────────────────────────")
    if not by_symbol:
        print("  No valid symbols.")
    else:
        print(f"  {'Symbol':<8} {'N':>4} {'P&L':>10} {'AvgMFE%':>9} {'AvgMAE%':>9} {'Giveback%':>10}")
        print(f"  {'-'*8} {'-'*4} {'-'*10} {'-'*9} {'-'*9} {'-'*10}")

        for sym, rows in sorted(by_symbol.items(), key=lambda x: sum(r["realized_pnl"] for r in x[1])):
            pnl = sum(r["realized_pnl"] for r in rows)
            print(
                f"  {sym:<8} {len(rows):>4} "
                f"${pnl:>+9.2f} "
                f"{avg([r.get('mfe_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('mae_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('profit_giveback_pct') for r in rows]):>10.1f}"
            )

    print()
    print("── By setup label ────────────────────────────────────")
    if not by_setup:
        print("  No setup labels.")
    else:
        print(f"  {'Setup':<28} {'N':>4} {'P&L':>10} {'AvgMFE%':>9} {'AvgMAE%':>9} {'Giveback%':>10}")
        print(f"  {'-'*28} {'-'*4} {'-'*10} {'-'*9} {'-'*9} {'-'*10}")

        for setup, rows in sorted(by_setup.items(), key=lambda x: sum(r["realized_pnl"] for r in x[1])):
            pnl = sum(r["realized_pnl"] for r in rows)
            print(
                f"  {setup:<28} {len(rows):>4} "
                f"${pnl:>+9.2f} "
                f"{avg([r.get('mfe_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('mae_pct') for r in rows]):>9.3f} "
                f"{avg([r.get('profit_giveback_pct') for r in rows]):>10.1f}"
            )


def print_trade_samples(results, limit=20):
    valid = [r for r in results if r and not r.get("error")]

    print()
    print("── Worst givebacks / trade management issues ─────────")
    givebacks = [
        r for r in valid
        if r.get("profit_giveback_pct") is not None
    ]
    givebacks = sorted(givebacks, key=lambda r: r.get("profit_giveback_pct") or 0, reverse=True)

    if not givebacks:
        print("  None.")
    else:
        print(
            f"  {'Exit time':<19} {'Sym':<6} {'P&L':>9} "
            f"{'MFE$':>9} {'MAE$':>9} {'Giveback%':>10} {'Class':<24} Setup"
        )
        for r in givebacks[:limit]:
            print(
                f"  {r['exit_timestamp']:<19} {r['symbol']:<6} "
                f"${r['realized_pnl']:>+8.2f} "
                f"${r['mfe_dollars']:>+8.2f} "
                f"${r['mae_dollars']:>+8.2f} "
                f"{str(r.get('profit_giveback_pct')):>10} "
                f"{r.get('excursion_classification'):<24} "
                f"{r.get('setup_label') or '-'}"
            )

    print()
    print("── Bad entries / never worked ────────────────────────")
    bad_entries = [
        r for r in valid
        if r.get("excursion_classification") in ("bad_entry_never_worked", "large_adverse_excursion")
    ]
    bad_entries = sorted(bad_entries, key=lambda r: r.get("mae_pct") or 0)

    if not bad_entries:
        print("  None.")
    else:
        print(
            f"  {'Exit time':<19} {'Sym':<6} {'P&L':>9} "
            f"{'MFE%':>8} {'MAE%':>8} {'Class':<24} Setup"
        )
        for r in bad_entries[:limit]:
            print(
                f"  {r['exit_timestamp']:<19} {r['symbol']:<6} "
                f"${r['realized_pnl']:>+8.2f} "
                f"{r.get('mfe_pct'):>8} "
                f"{r.get('mae_pct'):>8} "
                f"{r.get('excursion_classification'):<24} "
                f"{r.get('setup_label') or '-'}"
            )



def build_excursion_memory(results, target_date=None):
    valid = [r for r in results if r and not r.get("error")]

    by_symbol = defaultdict(list)
    by_setup = defaultdict(list)
    by_class = defaultdict(list)

    for r in valid:
        by_symbol[r["symbol"]].append(r)
        by_setup[r.get("setup_label") or "unknown"].append(r)
        by_class[r.get("excursion_classification") or "unknown"].append(r)

    def bucket(rows):
        n = len(rows)
        total_pnl = sum(float(r.get("realized_pnl") or 0) for r in rows)
        avg_mfe = avg([r.get("mfe_pct") for r in rows])
        avg_mae = avg([r.get("mae_pct") for r in rows])
        avg_giveback = avg([r.get("profit_giveback_pct") for r in rows])

        bad_entries = sum(1 for r in rows if r.get("excursion_classification") == "bad_entry_never_worked")
        winner_losers = sum(1 for r in rows if r.get("excursion_classification") == "winner_became_loser")
        givebacks = sum(1 for r in rows if r.get("excursion_classification") == "profit_giveback")

        if n < 2:
            recommendation = "observe"
            reason = f"sample too small: {n} closed trades"
        elif bad_entries / n >= 0.5:
            recommendation = "tighten_entries"
            reason = f"bad_entry_rate={bad_entries / n * 100:.1f}%"
        elif (winner_losers + givebacks) / n >= 0.5:
            recommendation = "improve_exits"
            reason = f"giveback_or_winner_loser_rate={(winner_losers + givebacks) / n * 100:.1f}%"
        elif total_pnl > 0 and avg_giveback < 40:
            recommendation = "working"
            reason = f"positive pnl ${total_pnl:.2f} with avg_giveback={avg_giveback:.1f}%"
        else:
            recommendation = "neutral"
            reason = f"mixed excursion profile, pnl=${total_pnl:.2f}"

        return {
            "trades": n,
            "total_pnl": round(total_pnl, 2),
            "avg_mfe_pct": round(avg_mfe, 3),
            "avg_mae_pct": round(avg_mae, 3),
            "avg_profit_giveback_pct": round(avg_giveback, 1),
            "bad_entry_count": bad_entries,
            "winner_became_loser_count": winner_losers,
            "profit_giveback_count": givebacks,
            "recommendation": recommendation,
            "reason": reason,
        }

    return {
        "generated_at": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
        "date": target_date,
        "trades_analyzed": len(results),
        "trades_with_bar_data": len(valid),
        "symbol_memory": {
            k: bucket(v)
            for k, v in sorted(by_symbol.items())
        },
        "setup_memory": {
            k: bucket(v)
            for k, v in sorted(by_setup.items())
        },
        "classification_memory": {
            k: bucket(v)
            for k, v in sorted(by_class.items())
        },
    }


def write_excursion_memory(results, target_date=None):
    memory = build_excursion_memory(results, target_date)
    atomic_write_json(EXCURSION_MEMORY_FILE, memory)
    print(f"Wrote {EXCURSION_MEMORY_FILE}")
    return memory

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Exit date YYYY-MM-DD. Default: all recent matched trades.")
    parser.add_argument("--symbol")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--write-memory", action="store_true", help="Write excursion_memory.json")
    args = parser.parse_args()

    print("=" * 72)
    title_date = args.date or "recent"
    print(f"  Excursion Report — {title_date}")
    print("=" * 72)

    rows = load_matched_trades(
        target_date=args.date,
        symbol=args.symbol,
        limit=args.limit,
    )

    print(f"Matched trades loaded: {len(rows)}")

    results = [analyze_trade(row) for row in rows]

    summarize(results)
    print_trade_samples(results, limit=args.samples)

    if args.write_memory:
        write_excursion_memory(results, args.date)

    errors = [r for r in results if r and r.get("error")]
    if errors:
        print()
        print("── Errors / skipped rows ─────────────────────────────")
        for r in errors[:10]:
            print(f"  id={r.get('id')} {r.get('symbol')}: {r.get('error')}")


if __name__ == "__main__":
    main()
