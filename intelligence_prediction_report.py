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


def table_exists(con, table_name):
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


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
        strong_join = ""
        strong_columns = """
                NULL AS strong_session_return_pct,
                NULL AS strong_primary_status,
                NULL AS strong_primary_blocker,
                NULL AS strong_auto_buy_candidates,
                NULL AS strong_auto_buy_max_score
        """
        if table_exists(con, "strong_day_participation"):
            strong_columns = """
                s.session_return_pct AS strong_session_return_pct,
                s.primary_status AS strong_primary_status,
                s.primary_blocker AS strong_primary_blocker,
                s.auto_buy_candidate_count AS strong_auto_buy_candidates,
                s.auto_buy_max_score AS strong_auto_buy_max_score
            """
            strong_join = """
            LEFT JOIN strong_day_participation s
              ON s.market_date = p.market_date
             AND s.symbol = p.symbol
             AND s.min_session_pct = (
                 SELECT MIN(min_session_pct)
                 FROM strong_day_participation
                 WHERE market_date = p.market_date
             )
            """
        rows = con.execute(
            f"""
            SELECT
                p.*,
                c.bias,
                c.risk_level,
                c.entry_quality,
                c.catalyst_score,
                c.supply_chain_risk_score,
                c.competitive_risk_score,
                {strong_columns}
            FROM daily_symbol_predictions p
            LEFT JOIN daily_symbol_context c
              ON c.market_date = p.market_date
             AND c.symbol = p.symbol
            {strong_join}
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
        f"{'Risk':<10} {'Strong%':>8} {'Strong Status':<22} {'Timing Rec':<28} Reason"
    )
    print(
        f"{'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*10} {'-'*9} "
        f"{'-'*9} {'-'*9} {'-'*6} {'-'*8} "
        f"{'-'*10} {'-'*8} {'-'*22} {'-'*28} {'-'*60}"
    )

    for r in rows:
        timing_score = "-" if r["timing_score"] is None else f"{float(r['timing_score']):.0f}"
        trend_score = "-" if r["trend_score"] is None else f"{float(r['trend_score']):.0f}"
        strong_pct = "-" if r["strong_session_return_pct"] is None else f"{float(r['strong_session_return_pct']):+.2f}%"
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
            f"{strong_pct:>8} "
            f"{short(r['strong_primary_status'], 22):<22} "
            f"{short(r['recommended_entry_timing'], 28):<28} "
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
    print("  Strong Status appears after strong_day_participation_report.py --write-db runs.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
