#!/usr/bin/env python3
"""
Lazy loader for portfolio_replacement_memory.json.

This is advisory/observe-only context for decision_context and reports.
It does not authorize automatic replacement or macro override.
"""

import json
import logging
from pathlib import Path

from policy_artifacts import policy_artifacts_enabled

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "portfolio_replacement_memory.json"

_memory = {}
_mtime = 0.0


def load_portfolio_replacement_memory():
    global _memory, _mtime

    if not policy_artifacts_enabled():
        return {
            "available": False,
            "reason": "policy artifacts disabled",
        }

    if not MEMORY_FILE.exists():
        return {
            "available": False,
            "reason": "portfolio_replacement_memory.json unavailable",
        }

    try:
        mtime = MEMORY_FILE.stat().st_mtime
        if mtime <= _mtime:
            return _memory

        data = json.loads(MEMORY_FILE.read_text())
        data["available"] = True
        _memory = data
        _mtime = mtime

        logger.info(
            "Portfolio replacement memory loaded: "
            f"recommendation={data.get('recommendation')} "
            f"generated_at={data.get('generated_at')}"
        )
        return _memory

    except Exception as e:
        logger.error(f"Failed to load portfolio replacement memory: {e}")
        return {
            "available": False,
            "reason": f"failed to parse portfolio_replacement_memory.json: {e}",
        }
