"""Auto-buy candidate adapter."""

from typing import Any

from src.trading_bot.signals.candidates import SignalCandidate, candidate_from_auto_buy


def auto_buy_candidate_from_raw(candidate: dict[str, Any]) -> SignalCandidate:
    return candidate_from_auto_buy(candidate)
