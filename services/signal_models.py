"""Typed contracts for the signal processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SignalContext:
    raw_signal: dict[str, Any]
    dedupe_key: str | None = None
    action: str | None = None
    symbol: str | None = None
    price: float | None = None
    account_state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionContext:
    signal: SignalContext
    trend: dict[str, Any] = field(default_factory=dict)
    setup: dict[str, Any] = field(default_factory=dict)
    session_momentum: dict[str, Any] = field(default_factory=dict)
    macro: dict[str, Any] = field(default_factory=dict)
    prediction: dict[str, Any] = field(default_factory=dict)
    strategy: dict[str, Any] = field(default_factory=dict)
    buy_opportunity: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalResult:
    approved: bool
    reason: str | None = None
    decision: dict[str, Any] = field(default_factory=dict)
    rejected_category: str | None = None


@dataclass
class SizingDecision:
    position_size_pct: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    reason: str | None = None


@dataclass
class ExecutionResult:
    submitted: bool = False
    order: dict[str, Any] | None = None
    status: str | None = None
    reason: str | None = None


@dataclass
class PipelineResult:
    handled: bool = True
    context: SignalContext | None = None
    approval: ApprovalResult | None = None
    sizing: SizingDecision | None = None
    execution: ExecutionResult | None = None
    error: Exception | None = None
