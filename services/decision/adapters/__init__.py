"""Canonical candidate adapters for decision inputs."""

from services.decision.adapters.auto_buy import auto_buy_candidate_from_raw
from services.decision.adapters.webhook import webhook_candidate_from_raw

__all__ = ["auto_buy_candidate_from_raw", "webhook_candidate_from_raw"]
