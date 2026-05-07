#!/usr/bin/env python3
"""
One-off backfill: query Alpaca for trades.db rows that have order_id but no
fill_price, and update fill_price + order_status if Alpaca shows them as
filled or partially_filled with a confirmed filled_avg_price.

Never uses signal_price as the confirmed fill — only writes when Alpaca
returns a real filled_avg_price.

Usage:
    python backfill_missing_fills.py            # apply updates
    python backfill_missing_fills.py --dry-run  # show what would change, don't write
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "trades.db"
ENV_FILE = Path("/etc/trading-bot.env")


def _load_env_if_needed():
    if os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY"):
        return
    if not ENV_FILE.exists():
        print(f"ERROR: ALPACA_API_KEY not set and {ENV_FILE} not found", file=sys.stderr)
        sys.exit(1)
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception as e:
        print(f"ERROR: Failed to read {ENV_FILE}: {e}", file=sys.stderr)
        sys.exit(1)


_load_env_if_needed()

from broker import api  # noqa: E402  (env must be loaded before broker import)


def find_missing_rows():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT id, timestamp, symbol, action, qty, signal_price, order_id, order_status
        FROM trades
        WHERE approved = 1
          AND action IN ('buy', 'sell')
          AND qty IS NOT NULL
          AND fill_price IS NULL
          AND order_id IS NOT NULL
        ORDER BY timestamp ASC
    """).fetchall()
    con.close()
    return rows


def update_row(row_id, status, fill_price):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE trades SET order_status = ?, fill_price = ? WHERE id = ?",
        (status, fill_price, row_id),
    )
    con.commit()
    con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing to DB")
    args = parser.parse_args()

    rows = find_missing_rows()
    print(f"Found {len(rows)} rows with approved=1, qty>0, fill_price=NULL, order_id present")
    if not rows:
        return

    updated = 0
    skipped = 0
    errors = 0

    for r in rows:
        oid = r["order_id"]
        try:
            order = api.get_order(oid)
        except Exception as e:
            print(f"  id={r['id']} {r['symbol']:<5} {r['action']:<4} order={oid[:8]}: ERROR querying Alpaca — {e}")
            errors += 1
            continue

        status = getattr(order, "status", None)
        filled_qty = getattr(order, "filled_qty", None)
        filled_avg_price = getattr(order, "filled_avg_price", None)

        if status in ("filled", "partially_filled") and filled_avg_price:
            try:
                fp = float(filled_avg_price)
            except (TypeError, ValueError):
                print(f"  id={r['id']} {r['symbol']:<5} {r['action']:<4} order={oid[:8]}: SKIP — cannot parse filled_avg_price={filled_avg_price!r}")
                skipped += 1
                continue
            print(f"  id={r['id']} {r['symbol']:<5} {r['action']:<4} order={oid[:8]}: APPLY status={status}, fill_price={fp}")
            if not args.dry_run:
                update_row(r["id"], status, fp)
            updated += 1
        else:
            print(f"  id={r['id']} {r['symbol']:<5} {r['action']:<4} order={oid[:8]}: SKIP — status={status} filled_qty={filled_qty} filled_avg_price={filled_avg_price}")
            skipped += 1

    print()
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"Errors:  {errors}")
    if args.dry_run:
        print("(dry-run — no DB changes written)")


if __name__ == "__main__":
    main()
