"""Compatibility re-export for the conviction policy package."""

from __future__ import annotations

from services.conviction import (
    conviction_active_for_mode,
    conviction_entry_decision,
    conviction_exit_decision,
)

__all__ = [
    "conviction_active_for_mode",
    "conviction_entry_decision",
    "conviction_exit_decision",
]
