#!/usr/bin/env python3
"""
Lazy strategy-memory loader for live trading decisions.

Reads strategy_memory.json produced by strategy_learner.py.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "strategy_memory.json"

_strategy_memory = {}
_strategy_memory_mtime = 0.0


def _load_strategy_memory():
    global _strategy_memory, _strategy_memory_mtime

    if not MEMORY_FILE.exists():
        return {}

    try:
        mtime = MEMORY_FILE.stat().st_mtime
        if mtime <= _strategy_memory_mtime:
            return _strategy_memory

        _strategy_memory = json.loads(MEMORY_FILE.read_text())
        _strategy_memory_mtime = mtime

        logger.info(
            "Strategy memory loaded: "
            f"trade_count={_strategy_memory.get('trade_count')} "
            f"generated_at={_strategy_memory.get('generated_at')}"
        )

    except Exception as e:
        logger.error(f"Failed to load strategy memory: {e}")
        _strategy_memory = {}

    return _strategy_memory


def memory_for_signal(symbol, setup_quality=None):
    """
    Return live memory adjustment for a symbol/setup.

    Output is intentionally simple:
    {
      "available": bool,
      "recommendation": "favor|neutral|caution|avoid|observe",
      "min_setup_score": int,
      "reason": str,
      "symbol_memory": {...}
    }
    """
    mem = _load_strategy_memory()
    if not mem:
        return {
            "available": False,
            "recommendation": "none",
            "min_setup_score": None,
            "reason": "strategy_memory.json unavailable",
        }

    symbol = (symbol or "").upper()
    symbols = mem.get("symbols") or {}
    symbol_mem = symbols.get(symbol)

    if not symbol_mem:
        return {
            "available": True,
            "recommendation": "observe",
            "min_setup_score": None,
            "reason": f"no symbol memory for {symbol}",
        }

    rec = symbol_mem.get("recommendation", "observe")
    min_score = symbol_mem.get("min_setup_score")

    return {
        "available": True,
        "recommendation": rec,
        "min_setup_score": min_score,
        "reason": symbol_mem.get("reason"),
        "symbol_memory": symbol_mem,
        "generated_at": mem.get("generated_at"),
        "lookback_days": mem.get("lookback_days"),
    }
