"""Conviction-mode entry/exit policy.

A low-frequency, high-selectivity strategy layer that sits on top of the
existing scanner. Entry requires convergence of independent evidence and
enforces scarcity; exit holds for the move with trailing/structure protection
rather than a fast scalp target.

The functions here are intentionally pure (plain inputs in, decision dict out)
so they can be unit-tested in isolation and replayed against logged paper
sessions without importing the broker SDK, the database, or the runtime.
"""

from __future__ import annotations

from .policy import (
    conviction_active_for_mode,
    conviction_entry_decision,
    conviction_exit_decision,
)

__all__ = [
    "conviction_active_for_mode",
    "conviction_entry_decision",
    "conviction_exit_decision",
]
