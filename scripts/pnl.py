#!/usr/bin/env python3
"""
Canonical P&L helpers for runtime risk checks.

This module should be the single source of truth for circuit-breaker daily
realized P&L. It only uses confirmed fills — never signal_price.
"""

from collections import defaultdict, deque
from datetime import date
from pathlib import Path

from repositories.reporting_repo import ReportingRepository

DB_PATH = Path(__file__).parent / "trades.db"


def get_daily_realized_pnl(target_date: str | None = None) -> float:
    """
    Compute realized P&L for a single trading date using confirmed filled rows.

    Rules:
    - Uses only approved buy/sell rows.
    - Requires qty and fill_price.
    - Requires order_status filled or partially_filled.
    - Never falls back to signal_price.
    - FIFO matches sells against earlier buys per symbol.
    """
    target_date = target_date or date.today().isoformat()

    rows = ReportingRepository(DB_PATH).daily_realized_pnl_rows(target_date)

    open_lots = defaultdict(deque)
    realized_pnl = 0.0

    for row in rows:
        symbol = row["symbol"]
        action = row["action"]
        qty = float(row["qty"] or 0)
        price = float(row["fill_price"] or 0)

        if not symbol or qty <= 0 or price <= 0:
            continue

        if action == "buy":
            open_lots[symbol].append({"qty": qty, "price": price})
            continue

        if action == "sell":
            remaining = qty

            while remaining > 0 and open_lots[symbol]:
                lot = open_lots[symbol][0]
                matched_qty = min(remaining, lot["qty"])

                realized_pnl += (price - lot["price"]) * matched_qty

                lot["qty"] -= matched_qty
                remaining -= matched_qty

                if lot["qty"] <= 0:
                    open_lots[symbol].popleft()

    return round(realized_pnl, 2)
