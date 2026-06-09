"""Canonical runtime decision package.

This package is the migration target for decision authority, traces, gates, and
candidate adapters. Legacy modules may still call into it while the larger
signal orchestration files are reduced to compatibility wrappers.
"""

from services.decision.engine import DecisionEngine, DecisionEvaluation

__all__ = ["DecisionEngine", "DecisionEvaluation"]
