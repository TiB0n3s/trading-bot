#!/usr/bin/env python3
"""
Insert synthetic baseline BUY rows for currently open Alpaca positions.

Use after a trades.db reset/recovery when Alpaca still has live positions but
the SQLite ledger is empty or incomplete.

This script is intentionally one-time/manual. It does not place orders.
"""

from datetime import datetime
from pathlib import Path

from broker import api
from db import DB_PATH, get_connection


BASELINE_REASON = "synthetic_position_baseline: after DB recovery 2026-05-23"


def main() -> int:
    positions = api.list_positions()

    if not positions:
        print("No open Alpaca positions found.")
        return 0

    inserted = 0
    skipped = 0
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(DB_PATH) as con:
        for p in positions:
            symbol = p.symbol
            qty = float(p.qty)
            avg_entry = float(p.avg_entry_price)

            if qty <= 0:
                print(f"SKIP {symbol}: qty={qty} is not a long position")
                skipped += 1
                continue

            existing = con.execute(
                """
                SELECT COUNT(*)
                FROM trades
                WHERE symbol = ?
                  AND rejection_reason LIKE 'synthetic_position_baseline:%'
                """,
                (symbol,),
            ).fetchone()[0]

            if existing:
                print(f"SKIP {symbol}: baseline already exists")
                skipped += 1
                continue

            con.execute(
                """
                INSERT INTO trades (
                    timestamp,
                    symbol,
                    action,
                    signal_price,
                    approved,
                    rejection_reason,
                    confidence,
                    position_size_pct,
                    stop_loss_pct,
                    take_profit_pct,
                    order_id,
                    order_status,
                    qty,
                    fill_price
                ) VALUES (?, ?, 'buy', ?, 1, ?, 'baseline', 0.0, 0.0, 0.0, ?, 'filled', ?, ?)
                """,
                (
                    timestamp,
                    symbol,
                    avg_entry,
                    BASELINE_REASON,
                    f"baseline-{symbol.lower()}-{timestamp.replace(' ', '-').replace(':', '')}",
                    int(qty),
                    avg_entry,
                ),
            )

            print(f"INSERT {symbol}: qty={qty} avg_entry={avg_entry}")
            inserted += 1

    print()
    print(f"Inserted: {inserted}")
    print(f"Skipped : {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
