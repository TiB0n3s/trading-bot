#!/usr/bin/env python3
"""Read-only live account snapshot for Deep Thought (Jarvis Tier 1).

NO TRADE AUTHORITY. This script calls ONLY the broker read endpoints
(``get_account``, ``list_positions``) and prints a stamped JSON snapshot of the
account plus open positions. There is no buy/sell/size/stage/submit/cancel call
anywhere in this file. The stamp ``live_positions_snapshot_no_trade_authority``
asserts that to Deep Thought's BotBridge, which refuses any payload lacking a
``no_..._trade_authority`` runtime_effect. Read-only by construction, like
scripts/benchmark_report.py.

Usage:
  python3 scripts/dt_positions_snapshot.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the bot package (src/) and scripts/ are importable, matching benchmark_report.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

RUNTIME_EFFECT = "live_positions_snapshot_no_trade_authority"


def _f(v):
    """Coerce Alpaca's stringy numerics to float; None on failure."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _snapshot() -> dict:
    from broker import api  # lazy Alpaca adapter; we touch only its READ methods

    acct = api.get_account()
    raw_positions = api.list_positions()

    account = {
        "buying_power": _f(getattr(acct, "buying_power", None)),
        "portfolio_value": _f(getattr(acct, "portfolio_value", None)),
        "cash": _f(getattr(acct, "cash", None)),
        "equity": _f(getattr(acct, "equity", None)),
        "account_status": str(getattr(acct, "status", "") or "") or None,
    }
    margin = {
        "maintenance_margin": _f(getattr(acct, "maintenance_margin", None)),
        "multiplier": getattr(acct, "multiplier", None),
        "daytrade_count": getattr(acct, "daytrade_count", None),
    }

    positions = []
    unrealized = 0.0
    for p in raw_positions:
        up = _f(getattr(p, "unrealized_pl", None))
        positions.append({
            "symbol": getattr(p, "symbol", None),
            "qty": _f(getattr(p, "qty", None)),
            "avg_entry_price": _f(getattr(p, "avg_entry_price", None)),
            "current_price": _f(getattr(p, "current_price", None)),
            "market_value": _f(getattr(p, "market_value", None)),
            "unrealized_pl": up,
        })
        if up is not None:
            unrealized += up

    snap = {
        "account": account,
        "margin": margin,
        "positions": positions,
        "unrealized_pnl": round(unrealized, 2),
        "positions_ok": True,
        "data_health": "ok",
    }

    # Realized P&L today is a nice-to-have; never let it fail the snapshot.
    try:
        from pnl import get_daily_realized_pnl
        snap["realized_pnl"] = _f(get_daily_realized_pnl())
    except Exception:
        snap["realized_pnl"] = None

    return snap


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Read-only live account snapshot (no trade authority)")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON (the only supported output mode)")
    ap.parse_args()

    snapshot = {
        "runtime_effect": RUNTIME_EFFECT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        snapshot.update(_snapshot())
    except Exception as exc:  # broker/network/credentials — fail soft, still stamped
        snapshot.update({
            "error": str(exc),
            "data_health": "degraded",
            "positions_ok": False,
            "positions": [],
        })
    print(json.dumps(snapshot, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
