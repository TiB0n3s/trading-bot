#!/usr/bin/env python3
"""
CLI helper for testing the deterministic trade scorer.

Usage:
  python3 -m strategy.score_signal_cli NVDA buy
  python3 -m strategy.score_signal_cli QQQ sell
"""

import json
import sys

from strategy.trade_scorer import score_trade


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python3 -m strategy.score_signal_cli SYMBOL buy|sell")
        return 2

    symbol = sys.argv[1].upper()
    action = sys.argv[2].lower()

    # Minimal mock trend/momentum so we can test without touching app.py.
    trend = {
        "direction": "bullish",
        "strength": "developing",
        "consecutive_count": 3,
    }

    momentum = {
        "direction": "rising",
        "momentum_pct": 0.25,
        "premarket_alignment": "confirmed",
    }

    alignment = {
        "benchmark": "QQQ",
        "aligned_for_buy": True,
    }

    thesis = score_trade(
        symbol=symbol,
        action=action,
        trend=trend,
        momentum=momentum,
        market_alignment=alignment,
    )

    print(json.dumps(thesis.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
