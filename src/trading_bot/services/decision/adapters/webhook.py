"""Webhook signal candidate adapter."""

from typing import Any

from trading_bot.signals.candidates import SignalCandidate, candidate_from_webhook


def webhook_candidate_from_raw(signal: dict[str, Any]) -> SignalCandidate:
    return candidate_from_webhook(signal)
