#!/usr/bin/env python3
"""
Score and insert a structured symbol event.

Usage:
  python3 score_symbol_event.py \
    --date 2026-05-26 \
    --symbol AAPL \
    --event-type product_launch \
    --summary "Apple is preparing a new product launch..." \
    --source manual_test

  python3 score_symbol_event.py --json /tmp/aapl_event.json
"""

import argparse
import json
from pathlib import Path

from market_intelligence.news_event_model import score_event
from market_intelligence.intelligence_store import insert_daily_symbol_event


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="Read base event from JSON file")

    parser.add_argument("--date", dest="market_date")
    parser.add_argument("--symbol")
    parser.add_argument("--event-type")
    parser.add_argument("--event-subtype")
    parser.add_argument("--summary")
    parser.add_argument("--source", default="manual_scored")
    parser.add_argument("--source-url")

    parser.add_argument("--product-name")
    parser.add_argument("--company-segment")
    parser.add_argument("--industry")

    parser.add_argument("--impact", dest="expected_market_impact")
    parser.add_argument("--relevance", dest="trade_relevance")
    parser.add_argument("--time-horizon")
    parser.add_argument("--confidence")

    # Optional manual overrides.
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

    parser.add_argument("--dry-run", action="store_true", help="Print scored event without DB insert")

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

    scored = score_event(event)

    print()
    print("=== Scored symbol event ===")
    print(f"  date        : {scored.get('market_date')}")
    print(f"  symbol      : {scored.get('symbol')}")
    print(f"  event_type  : {scored.get('event_type')}")
    print(f"  impact      : {scored.get('expected_market_impact')}")
    print(f"  relevance   : {scored.get('trade_relevance')}")
    print(f"  horizon     : {scored.get('time_horizon')}")
    print(f"  confidence  : {scored.get('confidence')}")
    print(f"  net_score   : {scored.get('net_event_score')}")
    print(f"  reason      : {scored.get('scoring_reason')}")
    print()
    print("  Scores:")
    for key in (
        "consumer_appetite_score",
        "revenue_impact_score",
        "profit_potential_score",
        "margin_risk_score",
        "supply_chain_risk_score",
        "materials_risk_score",
        "regulatory_risk_score",
        "competitive_risk_score",
        "execution_risk_score",
        "macro_risk_score",
    ):
        print(f"    {key:<30} {scored.get(key)}")

    if args.dry_run:
        print()
        print("Dry run only; not inserted.")
        print(json.dumps(scored, indent=2))
        return 0

    event_id = insert_daily_symbol_event(scored)

    print()
    print(f"Inserted daily_symbol_event id={event_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
