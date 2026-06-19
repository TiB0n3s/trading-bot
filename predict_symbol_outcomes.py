#!/usr/bin/env python3
"""
Generate observe-only symbol outcome predictions.

Usage:
  python3 predict_symbol_outcomes.py --date 2026-05-26
  python3 predict_symbol_outcomes.py --date 2026-05-26 --symbol AAPL
  python3 predict_symbol_outcomes.py --date 2026-05-26 --dry-run
"""

import argparse

from market_intelligence.experience_model import predict_all_symbols


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
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    predictions = predict_all_symbols(
        args.date,
        symbol=args.symbol,
        write=not args.dry_run,
    )

    print()
    print("=== Symbol outcome predictions ===")
    print(f"  Date    : {args.date}")
    print(f"  Symbol  : {args.symbol.upper() if args.symbol else '(all)'}")
    print(f"  Write   : {not args.dry_run}")
    print(f"  Count   : {len(predictions)}")
    print()
    print(f"  {'Sym':<7} {'Score':>7} {'P(profit)':>10} {'P(order)':>9} {'ExpPnL':>9} {'Conf':<9} {'Sample':>6} Reason")
    print(f"  {'-'*7} {'-'*7} {'-'*10} {'-'*9} {'-'*9} {'-'*9} {'-'*6} {'-'*70}")

    for p in sorted(predictions, key=lambda x: x.get("prediction_score") or 0, reverse=True):
        print(
            f"  {p['symbol']:<7} "
            f"{float(p.get('prediction_score') or 0):>7.2f} "
            f"{pct(p.get('probability_of_profit')):>10} "
            f"{pct(p.get('probability_of_order')):>9} "
            f"{money(p.get('expected_pnl')):>9} "
            f"{short(p.get('confidence'), 9):<9} "
            f"{int(p.get('sample_size') or 0):>6} "
            f"{short(p.get('reason'), 70)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
