"""Sizing stage interfaces for the signal pipeline."""

from __future__ import annotations

from services.signal_models import ApprovalResult, SizingDecision


class SizingService:
    def size(self, approval: ApprovalResult) -> SizingDecision:
        decision = approval.decision or {}
        return SizingDecision(
            position_size_pct=decision.get("position_size_pct"),
            stop_loss_pct=decision.get("stop_loss_pct"),
            take_profit_pct=decision.get("take_profit_pct"),
            reason=approval.reason,
        )
