#!/usr/bin/env python3
"""Read-only prior-session context for entry intelligence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.prior_session_context_service import build_default_prior_session_context_service

_services: dict[str, Any] = {}


def _service_for(db_path: Path | str | None):
    key = str(db_path or "__default__")
    if key not in _services:
        _services[key] = build_default_prior_session_context_service(db_path=db_path)
    return _services[key]


def prior_session_context(
    symbol: str,
    db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """
    Return the most recent strong_day_participation row for a symbol.

    Read-only. Intended for BUY signal context only; missing data returns None.
    """
    return _service_for(db_path).prior_session_context(symbol)
