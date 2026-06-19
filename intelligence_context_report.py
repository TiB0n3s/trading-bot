#!/usr/bin/env python3
"""
Daily symbol intelligence report.

Usage:
  python3 intelligence_context_report.py
  python3 intelligence_context_report.py --date 2026-05-26
  python3 intelligence_context_report.py --symbol AAPL
"""

import argparse
from collections import Counter
from datetime import date

from db import DB_PATH, get_connection
from market_intelligence.intelligence_store import init_intelligence_tables


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

    init_intelligence_tables()

    params = [args.date]
    symbol_sql = ""
    if args.symbol:
        symbol_sql = "AND symbol = ?"
        params.append(args.symbol.upper())

    with get_connection(DB_PATH) as con:
        rows = con.execute(
            f"""
            SELECT *
            FROM daily_symbol_context
            WHERE market_date = ?
              {symbol_sql}
            ORDER BY symbol
            """,
            params,
        ).fetchall()

        events = con.execute(
            f"""
            SELECT *
            FROM daily_symbol_events
            WHERE market_date = ?
              {symbol_sql}
            ORDER BY symbol, event_type
            """,
            params,
        ).fetchall()

    print("=" * 132)
    print(f"  Daily Symbol Intelligence — {args.date}")
    print("=" * 132)

    if not rows:
        print("No daily_symbol_context rows found.")
        return 1

    bias_counts = Counter(r["bias"] for r in rows)
    risk_counts = Counter(r["risk_level"] for r in rows)
    entry_counts = Counter(r["entry_quality"] for r in rows)

    sample = rows[0]

    print(f"  source          : {sample['source']}")
    print(f"  macro_sentiment : {sample['macro_sentiment']}")
    print(f"  macro_regime    : {sample['macro_regime']}")
    print(f"  risk_multiplier : {sample['risk_multiplier']}")
    print(f"  max_positions   : {sample['max_new_positions']}")
    print(f"  symbols         : {len(rows)}")
    print(f"  events          : {len(events)}")
    print(f"  bias_counts     : {dict(bias_counts)}")
    print(f"  risk_counts     : {dict(risk_counts)}")
    print(f"  entry_counts    : {dict(entry_counts)}")
    print()

    headers = [
        "Sym", "Bias", "Conf", "Risk", "Entry", "Daily%", "Intra%",
        "30m%", "RS", "Sector", "Index", "Reason"
    ]
    widths = [7, 8, 7, 10, 18, 8, 8, 8, 6, 12, 12, 38]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for r in rows:
        def pct(v):
            return "-" if v is None else f"{float(v):+.2f}"

        print(fmt.format(
            r["symbol"],
            short(r["bias"], 8),
            short(r["confidence"], 7),
            short(r["risk_level"], 10),
            short(r["entry_quality"], 18),
            pct(r["daily_pct"]),
            pct(r["intraday_pct"]),
            pct(r["momentum_30m_pct"]),
            "-" if r["relative_strength_score"] is None else f"{float(r['relative_strength_score']):.0f}",
            short(r["sector_alignment"], 12),
            short(r["index_alignment"], 12),
            short(r["reason"], 38),
        ))

    if events:
        print()
        print("── Events ─────────────────────────────────────────────")
        for e in events:
            print(
                f"  {e['symbol']:<7} {e['event_type']:<22} "
                f"impact={short(e['expected_market_impact'], 16):<16} "
                f"relevance={short(e['trade_relevance'], 18):<18} "
                f"{short(e['event_summary'], 70)}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
