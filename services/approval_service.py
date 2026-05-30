"""Approval stage interfaces for the signal pipeline."""

from __future__ import annotations

from services.signal_models import ApprovalResult, DecisionContext


class ApprovalService:
    def evaluate(self, context: DecisionContext) -> ApprovalResult:
        return ApprovalResult(approved=True, reason="deferred_to_legacy_processor")
