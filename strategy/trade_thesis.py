#!/usr/bin/env python3
"""
Structured trade thesis model.

This module does not place orders and does not change live behavior.
It gives the bot a consistent way to explain why a trade is attractive,
risky, or blocked.
"""

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class TradeThesis:
    symbol: str
    action: str
    approved_by_scorer: bool
    score: float
    setup_type: str
    macro_regime: str | None = None
    market_bias: str | None = None
    fundamental_score: str | None = None
    risk_level: str | None = None
    entry_quality: str | None = None
    trend_direction: str | None = None
    trend_strength: str | None = None
    momentum_direction: str | None = None
    momentum_pct: float | None = None
    benchmark: str | None = None
    benchmark_aligned: bool | None = None
    risk_factors: list[str] = field(default_factory=list)
    positive_factors: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
