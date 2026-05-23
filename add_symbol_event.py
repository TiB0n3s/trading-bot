#!/usr/bin/env python3
"""
Add a structured symbol event to daily_symbol_events.

Examples:
  python3 add_symbol_event.py \
    --date 2026-05-26 \
    --symbol AAPL \
    --event-type product_launch \
    --summary "Apple product launch thesis..." \
    --impact moderately_bullish \
    --relevance watch_for_confirmation \
    --consumer-appetite 70 \
    --profit-potential 62 \
    --supply-chain-risk 45

  python3 add_symbol_event.py --json /tmp/aapl_event.json
"""

import argparse
import json
from pathlib import Path

from market_intelligence.intelligence_store import insert_daily_symbol_event


def maybe_float(v):
    if v is None:
        return None
    return float(v)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="Read event payload from JSON file")

    parser.add_argument("--date", dest="market_date")
    parser.add_argument("--symbol")
    parser.add_argument("--event-type")
    parser.add_argument("--event-subtype")
    parser.add_argument("--summary")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--source-url")

    parser.add_argument("--product-name")
    parser.add_argument("--company-segment")
    parser.add_argument("--industry")

    parser.add_argument("--impact", dest="expected_market_impact")
    parser.add_argument("--relevance", dest="trade_relevance")
    parser.add_argument("--time-horizon")
    parser.add_argument("--confidence", default="medium")

    parser.add_argument("--consumer-appetite", type=float)
    parser.add_argument("--revenue-impact", type=float)
    parser.add_argument("--profit-potential", type=float)
    parser.add_argument("--margin-risk", type=float)
    parser.add_argument("--supply-chain-risk", type=float)
    parser.add_argument("--materials-risk", type=float)
    parser.add_argument("--regulatory-risk", type=float)
    parser.add_argument("--competitive-risk", type=float)
    parser.add_argument("--execution-risk", type=float)
    parser.add_argument("--macro-risk", type=float)

    args = parser.parse_args()

    if args.json:
        path = Path(args.json)
        if not path.exists():
            raise SystemExit(f"ERROR: JSON file not found: {path}")
        event = json.loads(path.read_text())
    else:
        event = {
            "market_date": args.market_date,
            "symbol": args.symbol.upper() if args.symbol else None,
            "event_type": args.event_type,
            "event_subtype": args.event_subtype,
            "event_summary": args.summary,
            "source": args.source,
            "source_url": args.source_url,
            "product_name": args.product_name,
            "company_segment": args.company_segment,
            "industry": args.industry,
            "expected_market_impact": args.expected_market_impact,
            "trade_relevance": args.trade_relevance,
            "time_horizon": args.time_horizon,
            "confidence": args.confidence,
            "consumer_appetite_score": args.consumer_appetite,
            "revenue_impact_score": args.revenue_impact,
            "profit_potential_score": args.profit_potential,
            "margin_risk_score": args.margin_risk,
            "supply_chain_risk_score": args.supply_chain_risk,
            "materials_risk_score": args.materials_risk,
            "regulatory_risk_score": args.regulatory_risk,
            "competitive_risk_score": args.competitive_risk,
            "execution_risk_score": args.execution_risk,
            "macro_risk_score": args.macro_risk,
        }

    event_id = insert_daily_symbol_event(event)

    print("Inserted daily_symbol_event")
    print(f"  id          : {event_id}")
    print(f"  date        : {event.get('market_date')}")
    print(f"  symbol      : {event.get('symbol')}")
    print(f"  event_type  : {event.get('event_type')}")
    print(f"  impact      : {event.get('expected_market_impact')}")
    print(f"  relevance   : {event.get('trade_relevance')}")


if __name__ == "__main__":
    main()
