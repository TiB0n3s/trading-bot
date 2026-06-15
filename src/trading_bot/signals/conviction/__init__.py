"""Compatibility namespace for conviction policy imports."""

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
