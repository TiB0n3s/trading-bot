#!/usr/bin/env python3
"""
Intelligence prediction report — read-only.

Displays observe-only daily_symbol_predictions.

Usage:
  python3 intelligence_prediction_report.py --date 2026-05-26
  python3 intelligence_prediction_report.py --date 2026-05-26 --symbol AAPL
"""

import argparse
from datetime import date

from db import DB_PATH, get_connection
from market_intelligence.experience_model import init_prediction_tables


def money(v):
    if v is None:
        return "-"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}${float(v):.2f}"


def pct(v):
    if v is None:
        return "-"
    return f"{float(v) * 100:.1f}%"


def short(v, width):
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--symbol")
    args = parser.parse_args()

    init_prediction_tables()

    params = [args.date]
    symbol_sql = ""
    if args.symbol:
        symbol_sql = "AND p.symbol = ?"
        params.append(args.symbol.upper())

    with get_connection(DB_PATH) as con:
        rows = con.execute(
            f"""
            SELECT
                p.*,
                c.bias,
                c.risk_level,
                c.entry_quality,
                c.catalyst_score,
                c.supply_chain_risk_score,
                c.competitive_risk_score
            FROM daily_symbol_predictions p
            LEFT JOIN daily_symbol_context c
              ON c.market_date = p.market_date
             AND c.symbol = p.symbol
            WHERE p.market_date = ?
              {symbol_sql}
            ORDER BY p.prediction_score DESC, p.symbol
            """,
            params,
        ).fetchall()

    print("=" * 132)
    print(f"  Intelligence Prediction Report — {args.date}")
    print("=" * 132)
    if args.symbol:
        print(f"  symbol filter : {args.symbol.upper()}")
    print(f"  predictions   : {len(rows)}")
    print()

    if not rows:
        print("No predictions found. Run:")
        print(f"  python3 predict_symbol_outcomes.py --date {args.date}")
        return 1

    print(
        f"{'Sym':<7} {'Score':>7} {'Timing':>7} {'Trend':>7} {'P(profit)':>10} {'P(order)':>9} "
        f"{'ExpPnL':>9} {'Conf':<9} {'Sample':>6} {'Bias':<8} "
        f"{'Risk':<10} {'Trend Label':<20} {'Timing Rec':<34} Reason"
    )
    print(
        f"{'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*10} {'-'*9} "
        f"{'-'*9} {'-'*9} {'-'*6} {'-'*8} "
        f"{'-'*10} {'-'*20} {'-'*34} {'-'*60}"
    )

    for r in rows:
        timing_score = "-" if r["timing_score"] is None else f"{float(r['timing_score']):.0f}"
        trend_score = "-" if r["trend_score"] is None else f"{float(r['trend_score']):.0f}"
        print(
            f"{r['symbol']:<7} "
            f"{float(r['prediction_score'] or 0):>7.2f} "
            f"{timing_score:>7} "
            f"{trend_score:>7} "
            f"{pct(r['probability_of_profit']):>10} "
            f"{pct(r['probability_of_order']):>9} "
            f"{money(r['expected_pnl']):>9} "
            f"{short(r['confidence'], 9):<9} "
            f"{int(r['sample_size'] or 0):>6} "
            f"{short(r['bias'], 8):<8} "
            f"{short(r['risk_level'], 10):<10} "
            f"{short(r['trend_label'], 20):<20} "
            f"{short(r['recommended_entry_timing'], 34):<34} "
            f"{short(r['reason'], 60)}"
        )

    print()
    print("Notes")
    print("-----")
    print("  Observe-only prediction layer. Does not alter live trading.")
    print("  Low/very_low confidence is expected until more sessions accumulate.")
    print("  Use this report to compare predictions against later realized outcomes.")
    print("  Timing Rec is observe-only and comes from historical signal timing lessons.")
    print("  Trend score/label are observe-only and come from historical trend context similarity.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
