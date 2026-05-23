#!/usr/bin/env python3
"""
Prediction validation report — read-only.

Compares daily_symbol_predictions against later signal/trade outcomes.

Usage:
  python3 prediction_validation_report.py
  python3 prediction_validation_report.py 2026-05-26

This report is safe to run before the session starts. If no outcomes exist yet,
it still shows prediction distribution and readiness.
"""

import argparse
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from db import DB_PATH, get_connection


def fmt(v, digits=2, blank="-"):
    if v is None:
        return blank
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return str(v)


def money(v):
    if v is None:
        return "-"
    try:
        v = float(v)
        sign = "+" if v >= 0 else ""
        return f"{sign}${v:.2f}"
    except Exception:
        return str(v)


def pct(v):
    if v is None:
        return "-"
    try:
        v = float(v)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"
    except Exception:
        return str(v)


def bucket_for_score(score):
    if score is None:
        return "unknown"
    score = float(score)
    if score >= 55:
        return "high_55_plus"
    if score >= 50:
        return "mid_50_55"
    if score >= 45:
        return "low_45_50"
    return "weak_below_45"


def avg(values):
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def section(title):
    print()
    print("── " + title + " " + "─" * max(0, 96 - len(title)))


def load_predictions(con, target_date):
    return con.execute("""
        SELECT
            market_date,
            symbol,
            prediction_score,
            probability_of_profit,
            probability_of_order,
            expected_pnl,
            expected_win_rate,
            confidence,
            sample_size,
            reason,
            timing_score,
            recommended_entry_timing,
            trend_score,
            trend_label,
            trend_regime,
            trend_confidence,
            trend_reason
        FROM daily_symbol_predictions
        WHERE market_date = ?
        ORDER BY prediction_score DESC, symbol
    """, (target_date,)).fetchall()


def load_signal_outcomes(con, target_date):
    rows = con.execute("""
        SELECT
            symbol,
            COUNT(*) AS signals,
            SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected,
            SUM(CASE WHEN realized_pnl IS NOT NULL THEN 1 ELSE 0 END) AS closed_signals,
            SUM(COALESCE(realized_pnl, 0)) AS realized_pnl,
            AVG(realized_pnl) AS avg_realized_pnl,
            AVG(realized_pnl_pct) AS avg_realized_pnl_pct,
            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) AS losses
        FROM historical_signal_outcomes
        WHERE market_date = ?
        GROUP BY symbol
    """, (target_date,)).fetchall()
    return {r["symbol"]: r for r in rows}


def load_trade_outcomes(con, target_date):
    rows = con.execute("""
        SELECT
            symbol,
            COUNT(*) AS trades,
            SUM(COALESCE(realized_pnl, 0)) AS realized_pnl,
            AVG(realized_pnl) AS avg_realized_pnl,
            AVG(realized_pnl_pct) AS avg_realized_pnl_pct,
            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) AS losses
        FROM historical_trade_outcomes
        WHERE date(exit_timestamp) = ?
        GROUP BY symbol
    """, (target_date,)).fetchall()
    return {r["symbol"]: r for r in rows}


def load_matched_trades(con, target_date):
    rows = con.execute("""
        SELECT
            symbol,
            COUNT(*) AS matched_trades,
            SUM(COALESCE(realized_pnl, 0)) AS realized_pnl,
            AVG(realized_pnl) AS avg_realized_pnl,
            AVG(realized_pnl_pct) AS avg_realized_pnl_pct,
            SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN won = 0 THEN 1 ELSE 0 END) AS losses
        FROM matched_trades
        WHERE date(exit_timestamp) = ?
        GROUP BY symbol
    """, (target_date,)).fetchall()
    return {r["symbol"]: r for r in rows}


def render_readiness(preds, sig, trades, matched):
    section("Readiness")
    print(f"  Predictions          : {len(preds)}")
    print(f"  Symbols with signals : {len(sig)}")
    print(f"  Symbols with trades  : {len(trades)}")
    print(f"  Symbols with matches : {len(matched)}")

    if not preds:
        print()
        print("  [FAIL] No daily_symbol_predictions rows found for this date.")
        return

    if not sig and not trades and not matched:
        print()
        print("  [OK] Pre-session mode: predictions exist, but outcomes have not populated yet.")
        print("       Re-run after the session to validate forecast quality.")


def render_prediction_distribution(preds):
    section("Prediction Distribution")
    buckets = defaultdict(list)
    for r in preds:
        buckets[bucket_for_score(r["prediction_score"])].append(r)

    print(f"  {'Bucket':<18} {'N':>4} {'AvgScore':>9} {'AvgTiming':>9} {'AvgTrend':>9}")
    print(f"  {'-'*18} {'-'*4} {'-'*9} {'-'*9} {'-'*9}")

    order = ["high_55_plus", "mid_50_55", "low_45_50", "weak_below_45", "unknown"]
    for b in order:
        rows = buckets.get(b, [])
        if not rows:
            continue
        print(
            f"  {b:<18} {len(rows):>4} "
            f"{fmt(avg([r['prediction_score'] for r in rows]), 2):>9} "
            f"{fmt(avg([r['timing_score'] for r in rows]), 2):>9} "
            f"{fmt(avg([r['trend_score'] for r in rows]), 2):>9}"
        )


def render_top_bottom(preds, limit=10):
    section("Top / Bottom Predictions")
    print("  Top candidates")
    print(f"  {'Sym':<7} {'Score':>7} {'Timing':>7} {'Trend':>7} {'TrendLabel':<22} {'TimingRec':<34}")
    print(f"  {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*22} {'-'*34}")
    for r in preds[:limit]:
        print(
            f"  {r['symbol']:<7} "
            f"{fmt(r['prediction_score'], 2):>7} "
            f"{fmt(r['timing_score'], 0):>7} "
            f"{fmt(r['trend_score'], 0):>7} "
            f"{str(r['trend_label'] or '-'):<22} "
            f"{str(r['recommended_entry_timing'] or '-')[:34]:<34}"
        )

    print()
    print("  Weakest candidates")
    print(f"  {'Sym':<7} {'Score':>7} {'Timing':>7} {'Trend':>7} {'TrendLabel':<22} {'TimingRec':<34}")
    print(f"  {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*22} {'-'*34}")
    for r in list(reversed(preds[-limit:])):
        print(
            f"  {r['symbol']:<7} "
            f"{fmt(r['prediction_score'], 2):>7} "
            f"{fmt(r['timing_score'], 0):>7} "
            f"{fmt(r['trend_score'], 0):>7} "
            f"{str(r['trend_label'] or '-'):<22} "
            f"{str(r['recommended_entry_timing'] or '-')[:34]:<34}"
        )


def render_outcome_by_bucket(preds, sig, trades, matched):
    section("Outcome By Prediction Bucket")
    any_outcome = bool(sig or trades or matched)

    if not any_outcome:
        print("  No signal/trade outcomes yet for this date.")
        return

    groups = defaultdict(list)
    for r in preds:
        groups[bucket_for_score(r["prediction_score"])].append(r)

    print(
        f"  {'Bucket':<18} {'N':>4} {'Signals':>7} {'Appr%':>7} "
        f"{'Closed':>7} {'SigPnL':>10} {'Trades':>7} {'TradePnL':>10} {'Matches':>7} {'MatchPnL':>10}"
    )
    print(
        f"  {'-'*18} {'-'*4} {'-'*7} {'-'*7} "
        f"{'-'*7} {'-'*10} {'-'*7} {'-'*10} {'-'*7} {'-'*10}"
    )

    for b in ["high_55_plus", "mid_50_55", "low_45_50", "weak_below_45", "unknown"]:
        rows = groups.get(b, [])
        if not rows:
            continue

        symbols = [r["symbol"] for r in rows]

        signals = sum((sig.get(s) or {}).get("signals") or 0 for s in symbols)
        approved = sum((sig.get(s) or {}).get("approved") or 0 for s in symbols)
        closed = sum((sig.get(s) or {}).get("closed_signals") or 0 for s in symbols)
        sig_pnl = sum((sig.get(s) or {}).get("realized_pnl") or 0 for s in symbols)

        trade_count = sum((trades.get(s) or {}).get("trades") or 0 for s in symbols)
        trade_pnl = sum((trades.get(s) or {}).get("realized_pnl") or 0 for s in symbols)

        match_count = sum((matched.get(s) or {}).get("matched_trades") or 0 for s in symbols)
        match_pnl = sum((matched.get(s) or {}).get("realized_pnl") or 0 for s in symbols)

        appr_pct = (approved / signals * 100) if signals else 0

        print(
            f"  {b:<18} {len(rows):>4} {signals:>7} {appr_pct:>6.1f}% "
            f"{closed:>7} {money(sig_pnl):>10} {trade_count:>7} {money(trade_pnl):>10} "
            f"{match_count:>7} {money(match_pnl):>10}"
        )


def render_timing_and_trend(preds, sig, matched):
    section("Timing / Trend Readout")

    by_timing = defaultdict(list)
    by_trend = defaultdict(list)

    for r in preds:
        by_timing[r["recommended_entry_timing"] or "unknown"].append(r)
        by_trend[r["trend_label"] or "unknown"].append(r)

    print("  By recommended entry timing")
    print(f"  {'Timing':<38} {'N':>4} {'AvgScore':>9} {'Signals':>7} {'SigPnL':>10}")
    print(f"  {'-'*38} {'-'*4} {'-'*9} {'-'*7} {'-'*10}")
    for label, rows in sorted(by_timing.items(), key=lambda x: -len(x[1])):
        symbols = [r["symbol"] for r in rows]
        signals = sum((sig.get(s) or {}).get("signals") or 0 for s in symbols)
        sig_pnl = sum((sig.get(s) or {}).get("realized_pnl") or 0 for s in symbols)
        print(
            f"  {label[:38]:<38} {len(rows):>4} "
            f"{fmt(avg([r['prediction_score'] for r in rows]), 2):>9} "
            f"{signals:>7} {money(sig_pnl):>10}"
        )

    print()
    print("  By trend label")
    print(f"  {'TrendLabel':<24} {'N':>4} {'AvgScore':>9} {'Matches':>7} {'MatchPnL':>10}")
    print(f"  {'-'*24} {'-'*4} {'-'*9} {'-'*7} {'-'*10}")
    for label, rows in sorted(by_trend.items(), key=lambda x: -len(x[1])):
        symbols = [r["symbol"] for r in rows]
        match_count = sum((matched.get(s) or {}).get("matched_trades") or 0 for s in symbols)
        match_pnl = sum((matched.get(s) or {}).get("realized_pnl") or 0 for s in symbols)
        print(
            f"  {label[:24]:<24} {len(rows):>4} "
            f"{fmt(avg([r['prediction_score'] for r in rows]), 2):>9} "
            f"{match_count:>7} {money(match_pnl):>10}"
        )


def render_notes():
    section("Notes")
    print("  This report is read-only and does not place/cancel/modify orders.")
    print("  Pre-session runs validate that predictions exist and show score distribution.")
    print("  Post-session runs compare prediction buckets to signal/trade outcomes.")
    print("  Very-low confidence is expected while historical context sample sizes are small.")


def main():
    parser = argparse.ArgumentParser(description="Prediction validation report — read-only.")
    parser.add_argument("date_arg", nargs="?", help="Date YYYY-MM-DD")
    parser.add_argument("--date", dest="date_opt", help="Date YYYY-MM-DD")
    args = parser.parse_args()

    target_date = args.date_opt or args.date_arg or date.today().isoformat()

    print("=" * 120)
    print(f"  Prediction Validation Report — {target_date}")
    print("=" * 120)

    with get_connection(DB_PATH) as con:
        preds = load_predictions(con, target_date)
        sig = load_signal_outcomes(con, target_date)
        trades = load_trade_outcomes(con, target_date)
        matched = load_matched_trades(con, target_date)

    render_readiness(preds, sig, trades, matched)

    if not preds:
        render_notes()
        return 1

    render_prediction_distribution(preds)
    render_top_bottom(preds)
    render_outcome_by_bucket(preds, sig, trades, matched)
    render_timing_and_trend(preds, sig, matched)
    render_notes()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
