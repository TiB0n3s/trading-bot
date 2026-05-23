#!/usr/bin/env python3
"""
Raw research template generator.

Creates a raw research JSON scaffold compatible with market_brief_builder.py.

This is useful for:
- validating the richer brief pipeline
- giving pre_market_research.py a target output shape
- manually drafting/overriding research without touching live market_context.json

This script does not place orders or modify market_context.json unless you pass
an output path that points there.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pytz

# Allow running this file directly as:
#   python3 market_intelligence/raw_research_template.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from symbols_config import APPROVED_SYMBOLS

ET = pytz.timezone("America/New_York")


def default_symbol(symbol: str) -> dict:
    return {
        "bias": "neutral",
        "reason": "Research pending.",
        "confidence": "low",
        "fundamental_score": "neutral",
        "risk_level": "medium",
        "entry_quality": "conditional",
        "avoid_type": None,
        "catalyst_score": 3,
        "relative_strength_score": 5,
        "sector_alignment": "mixed",
        "index_alignment": "mixed",
        "liquidity_quality": "acceptable",
        "volume_context": "normal",
        "price_location": "range_bound",
        "key_catalysts": [],
        "key_risks": [],
        "support_levels": [],
        "resistance_levels": [],
        "notes": None,
    }


def build_template(market_date: str | None = None) -> dict:
    today = datetime.now(ET).date().isoformat()

    return {
        "market_date": market_date or today,
        "generated_at": datetime.now(ET).isoformat(),
        "macro_sentiment": "mixed",
        "macro_regime": "caution",
        "risk_multiplier": 0.75,
        "max_new_positions": 6,
        "block_new_buys": False,
        "macro_summary": "Research pending.",
        "index_state": {
            "SPY": {
                "trend": "mixed",
                "premarket_gap_pct": None,
                "above_vwap": None,
                "key_levels": [],
                "notes": "Research pending.",
            },
            "QQQ": {
                "trend": "mixed",
                "premarket_gap_pct": None,
                "above_vwap": None,
                "key_levels": [],
                "notes": "Research pending.",
            },
            "IWM": {
                "trend": "mixed",
                "premarket_gap_pct": None,
                "above_vwap": None,
                "key_levels": [],
                "notes": "Research pending.",
            },
            "GLD": {
                "trend": "mixed",
                "premarket_gap_pct": None,
                "above_vwap": None,
                "key_levels": [],
                "notes": "Research pending.",
            },
        },
        "sector_state": {
            "mega_cap_tech": {"trend": "mixed", "risk": "medium", "notes": "Research pending."},
            "semiconductors": {"trend": "mixed", "risk": "medium", "notes": "Research pending."},
            "energy": {"trend": "mixed", "risk": "medium", "notes": "Research pending."},
            "industrials": {"trend": "mixed", "risk": "medium", "notes": "Research pending."},
            "defense": {"trend": "mixed", "risk": "medium", "notes": "Research pending."},
            "healthcare_biotech": {"trend": "mixed", "risk": "medium", "notes": "Research pending."},
            "consumer_retail": {"trend": "mixed", "risk": "medium", "notes": "Research pending."},
            "payments": {"trend": "mixed", "risk": "medium", "notes": "Research pending."},
        },
        "macro_events": [],
        "symbols": {
            symbol: default_symbol(symbol)
            for symbol in sorted(APPROVED_SYMBOLS)
        },
        "source": "raw_research_template",
        "format": "raw_research_v1",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="market_date", help="Market date YYYY-MM-DD")
    parser.add_argument(
        "--output",
        default="/tmp/raw_market_research_template.json",
        help="Output path, default /tmp/raw_market_research_template.json",
    )
    args = parser.parse_args()

    template = build_template(args.market_date)
    output = Path(args.output)
    output.write_text(json.dumps(template, indent=2, sort_keys=True) + "\n")

    print(f"Wrote {output}")
    print(f"market_date={template['market_date']}")
    print(f"symbols={len(template['symbols'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
