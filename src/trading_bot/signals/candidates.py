"""Canonical signal/candidate contracts for webhook and auto-buy paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CandidateSource = Literal["webhook", "auto_buy", "manual", "external_discovery"]


@dataclass(frozen=True)
class SignalCandidate:
    symbol: str
    action: str
    source: CandidateSource
    price: float | None = None
    candidate_id: str | None = None
    confidence: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_legacy_signal(self) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "action": self.action,
            "source": self.source,
        }
        if self.price is not None:
            payload["price"] = self.price
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.candidate_id is not None:
            payload["candidate_id"] = self.candidate_id
        payload.update(self.features)
        return payload


def candidate_from_webhook(signal: dict[str, Any]) -> SignalCandidate:
    price = signal.get("price") or signal.get("signal_price")
    try:
        price_f = float(price) if price is not None else None
    except Exception:
        price_f = None
    return SignalCandidate(
        symbol=str(signal.get("symbol") or "").upper(),
        action=str(signal.get("action") or "buy").lower(),
        source="webhook",
        price=price_f,
        confidence=signal.get("confidence"),
        raw=dict(signal),
    )


def candidate_from_auto_buy(candidate: dict[str, Any]) -> SignalCandidate:
    price = candidate.get("price") or candidate.get("signal_price") or candidate.get("close")
    try:
        price_f = float(price) if price is not None else None
    except Exception:
        price_f = None
    return SignalCandidate(
        symbol=str(candidate.get("symbol") or "").upper(),
        action=str(candidate.get("action") or "buy").lower(),
        source="auto_buy",
        price=price_f,
        candidate_id=str(candidate.get("candidate_id") or candidate.get("id") or ""),
        confidence=candidate.get("confidence"),
        features={
            key: value
            for key, value in candidate.items()
            if key not in {"symbol", "action", "price", "signal_price", "close", "id"}
        },
        raw=dict(candidate),
    )
