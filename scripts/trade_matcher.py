#!/usr/bin/env python3
"""Compatibility wrapper and CLI for FIFO matched-trade rebuilds."""

from __future__ import annotations

from services.trade_matcher_service import (
    TradeMatcherService,
    build_default_trade_matcher_service,
)

_DEFAULT_SERVICE: TradeMatcherService | None = None


def _service() -> TradeMatcherService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = build_default_trade_matcher_service()
    return _DEFAULT_SERVICE


def load_filled_trades():
    return _service().load_filled_trades()


def match_trades():
    return _service().match_trades()


def init_matched_trades_table():
    return _service().init_matched_trades_table()


def rebuild_matched_trades():
    return _service().rebuild_matched_trades()


def main():
    matched, open_lots = rebuild_matched_trades()

    print("Matched trades:", len(matched))
    print()

    realized = sum(t["realized_pnl"] for t in matched)
    wins = [t for t in matched if t["realized_pnl"] > 0]
    losses = [t for t in matched if t["realized_pnl"] < 0]

    print(f"Realized P&L: ${realized:.2f}")
    print(f"Wins: {len(wins)}")
    print(f"Losses: {len(losses)}")

    if matched:
        print(f"Win rate: {len(wins) / len(matched) * 100:.1f}%")
        print(f"Expectancy: ${realized / len(matched):.2f} per matched trade")

    print()
    print("Recent matched trades:")
    for t in matched[-10:]:
        print(
            f"{t['symbol']} qty={t['qty']} "
            f"{t['entry_price']} -> {t['exit_price']} "
            f"PnL=${t['realized_pnl']} "
            f"hold={t['holding_minutes']}m "
            f"trend={t.get('trend_direction')}/{t.get('trend_strength')} "
            f"setup={t.get('setup_label')}/{t.get('setup_policy_action')} "
            f"session={t.get('session_trend_label')}/{t.get('session_trend_score')} "
            f"prediction={t.get('prediction_score')}/{t.get('prediction_decision')} "
            f"buy_opp={t.get('buy_opportunity_score')}/{t.get('buy_opportunity_recommendation')} "
            f"macro={t.get('macro_regime')}"
        )

    print()
    print("Open lots:")
    for symbol, lots in open_lots.items():
        open_qty = sum(lot["qty"] for lot in lots)
        if open_qty > 0:
            print(f"{symbol}: {open_qty} shares across {len(lots)} lots")


if __name__ == "__main__":
    main()
