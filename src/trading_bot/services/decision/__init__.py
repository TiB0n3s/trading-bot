"""Canonical runtime decision package.

This package is the migration target for decision authority, traces, gates, and
candidate adapters. Legacy modules may still call into it while the larger
signal orchestration files are reduced to compatibility wrappers.
"""

from .capital_allocator import CapitalAllocation, CapitalAllocator
from .engine import DecisionEngine, DecisionEvaluation
from .orchestrator import CanonicalDecisionOrchestrator

__all__ = [
    "CanonicalDecisionOrchestrator",
    "CapitalAllocation",
    "CapitalAllocator",
    "DecisionEngine",
    "DecisionEvaluation",
]
