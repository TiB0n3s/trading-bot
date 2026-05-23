#!/usr/bin/env python3
"""
Aggregate daily_symbol_events into daily_symbol_context.

Usage:
  python3 apply_event_scores.py --date 2026-05-26
  python3 apply_event_scores.py --date 2026-05-26 --symbol AAPL
"""

import argparse

from market_intelligence.intelligence_store import update_daily_context_from_events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol")
    args = parser.parse_args()

    result = update_daily_context_from_events(args.date, args.symbol)

    print()
    print("=== Event scores applied to daily context ===")
    print(f"  Date              : {result['market_date']}")
    print(f"  Symbol filter     : {result['symbol'] or '(all)'}")
    print(f"  Updated           : {result['updated']}")
    print(f"  Skipped no events : {result['skipped_no_events']}")

    if result["summaries"]:
        print()
        print(f"  {'Symbol':<7} {'Events':>6} {'Catalyst':>9} {'Demand':>8} {'Revenue':>8} {'Profit':>8} {'SupplyRisk':>11} {'MatRisk':>8} {'CompRisk':>8}")
        print(f"  {'-'*7} {'-'*6} {'-'*9} {'-'*8} {'-'*8} {'-'*8} {'-'*11} {'-'*8} {'-'*8}")
        for s in result["summaries"]:
            print(
                f"  {s['symbol']:<7} "
                f"{s['event_count']:>6} "
                f"{str(s.get('catalyst_score')):>9} "
                f"{str(s.get('consumer_appetite_score')):>8} "
                f"{str(s.get('revenue_impact_score')):>8} "
                f"{str(s.get('profit_potential_score')):>8} "
                f"{str(s.get('supply_chain_risk_score')):>11} "
                f"{str(s.get('materials_risk_score')):>8} "
                f"{str(s.get('competitive_risk_score')):>8}"
            )


if __name__ == "__main__":
    main()
