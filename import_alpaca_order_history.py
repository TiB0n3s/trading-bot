#!/usr/bin/env python3
"""
Import pasted Alpaca order-history text into separate learning tables.

This does NOT modify trades.
This does NOT modify matched_trades.
This does NOT affect live reconciliation.

It creates:
- external_alpaca_orders
- historical_trade_outcomes

Usage:
  python3 import_alpaca_order_history.py /tmp/alpaca_orders_may18_22.txt --dry-run
  python3 import_alpaca_order_history.py /tmp/alpaca_orders_may18_22.txt
"""

import argparse
import re
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from db import DB_PATH, get_connection


MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def clean_num(value):
    if value is None:
        return None
    value = str(value).strip().replace(",", "")
    if value in ("", "-", "None"):
        return None
    return float(value)


def parse_datetime(value):
    if not value or value == "-":
        return None

    value = value.strip()
    # Example: May 22, 2026, 02:56:05 PM
    m = re.match(
        r"^([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4}),\s+(\d{1,2}):(\d{2}):(\d{2})\s+(AM|PM)$",
        value,
    )
    if not m:
        return None

    mon, day, year, hour, minute, second, ampm = m.groups()
    hour = int(hour)
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0

    dt = datetime(
        int(year),
        MONTHS[mon[:3]],
        int(day),
        hour,
        int(minute),
        int(second),
    )
    return dt.isoformat(sep=" ")


def order_type_and_price(value):
    value = value.strip()
    if value.lower() == "market":
        return "market", None
    m = re.match(r"^(Limit|Stop)\s+@\s+\$?([\d,]+(?:\.\d+)?)$", value, re.I)
    if m:
        return m.group(1).lower(), clean_num(m.group(2))
    return value.lower(), None


def split_rows(text):
    """Parse the copied Alpaca table.

    The pasted format is line-oriented:
      SYMBOL
      Order Type   side qty filled_qty avg_fill status source submitted filled expires
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rows = []

    i = 0
    while i < len(lines):
        symbol = lines[i].strip()

        if symbol.lower() in {
            "asset",
            "order type",
            "side",
            "qty",
            "filled qty",
            "avg. fill price",
            "status",
            "source",
            "submitted at",
            "filled at",
            "expires at",
        }:
            i += 1
            continue

        if i + 1 >= len(lines):
            break

        detail = lines[i + 1]
        parts = re.split(r"\t+", detail)

        # Some pasted rows may collapse spacing. Prefer tab split, but fallback
        # to a regex for known order type prefix.
        if len(parts) < 9:
            m = re.match(
                r"^(Market|Limit @ \$?[\d,]+(?:\.\d+)?|Stop @ \$?[\d,]+(?:\.\d+)?)\s+"
                r"(buy|sell)\s+"
                r"([\d,]+(?:\.\d+)?)\s+"
                r"([\d,]+(?:\.\d+)?)\s+"
                r"(-|[\d,]+(?:\.\d+)?)\s+"
                r"(\w+)\s+"
                r"(\S+)\s+"
                r"(.+?)\s+"
                r"(.+?|-)\s+"
                r"(.+)$",
                detail,
                re.I,
            )
            if not m:
                i += 1
                continue
            parts = list(m.groups())

        if len(parts) >= 10:
            order_type_raw = parts[0]
            side = parts[1].lower()
            qty = clean_num(parts[2])
            filled_qty = clean_num(parts[3])
            avg_fill_price = clean_num(parts[4])
            status = parts[5].lower()
            source = parts[6]
            submitted_at = parts[7]
            filled_at = parts[8]
            expires_at = parts[9]
        else:
            i += 1
            continue

        order_type, limit_stop_price = order_type_and_price(order_type_raw)

        rows.append({
            "symbol": symbol.upper(),
            "order_type_raw": order_type_raw,
            "order_type": order_type,
            "limit_stop_price": limit_stop_price,
            "side": side,
            "qty": qty,
            "filled_qty": filled_qty,
            "avg_fill_price": avg_fill_price,
            "status": status,
            "source": source,
            "submitted_at": parse_datetime(submitted_at),
            "filled_at": parse_datetime(filled_at),
            "expires_at": parse_datetime(expires_at),
            "raw_detail": detail,
        })

        i += 2

    return rows


def init_tables():
    with get_connection(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS external_alpaca_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                order_type_raw TEXT,
                order_type TEXT,
                limit_stop_price REAL,
                side TEXT,
                qty REAL,
                filled_qty REAL,
                avg_fill_price REAL,
                status TEXT,
                source TEXT,
                submitted_at TEXT,
                filled_at TEXT,
                expires_at TEXT,
                raw_detail TEXT,
                imported_at TEXT NOT NULL,
                UNIQUE(symbol, side, order_type_raw, qty, filled_qty, avg_fill_price, status, submitted_at, filled_at)
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS historical_trade_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                symbol TEXT NOT NULL,
                entry_timestamp TEXT,
                exit_timestamp TEXT,
                holding_minutes REAL,
                qty REAL,
                entry_price REAL,
                exit_price REAL,
                realized_pnl REAL,
                realized_pnl_pct REAL,
                exit_type TEXT,
                raw_json TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(source, symbol, entry_timestamp, exit_timestamp, qty, entry_price, exit_price)
            )
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_external_alpaca_orders_symbol_time
            ON external_alpaca_orders(symbol, submitted_at, filled_at)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_historical_trade_outcomes_symbol_exit
            ON historical_trade_outcomes(symbol, exit_timestamp)
        """)


def insert_orders(rows):
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    inserted = 0

    with get_connection(DB_PATH) as con:
        for r in rows:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO external_alpaca_orders (
                    symbol, order_type_raw, order_type, limit_stop_price,
                    side, qty, filled_qty, avg_fill_price, status, source,
                    submitted_at, filled_at, expires_at, raw_detail, imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["symbol"],
                    r["order_type_raw"],
                    r["order_type"],
                    r["limit_stop_price"],
                    r["side"],
                    r["qty"],
                    r["filled_qty"],
                    r["avg_fill_price"],
                    r["status"],
                    r["source"],
                    r["submitted_at"],
                    r["filled_at"],
                    r["expires_at"],
                    r["raw_detail"],
                    now,
                ),
            )
            inserted += cur.rowcount

    return inserted


def build_outcomes_from_orders(rows):
    """FIFO-match filled buys/sells by symbol."""
    filled = [
        r for r in rows
        if r["status"] == "filled"
        and r["filled_qty"]
        and r["avg_fill_price"]
        and r["filled_at"]
        and r["side"] in ("buy", "sell")
    ]

    filled.sort(key=lambda r: (r["filled_at"], r["symbol"], r["side"]))

    lots = defaultdict(deque)
    outcomes = []

    for r in filled:
        sym = r["symbol"]
        qty = float(r["filled_qty"])
        price = float(r["avg_fill_price"])

        if r["side"] == "buy":
            lots[sym].append({
                "timestamp": r["filled_at"],
                "qty": qty,
                "price": price,
                "raw": r,
            })
            continue

        # Sell: consume buy lots.
        remaining = qty
        while remaining > 0 and lots[sym]:
            lot = lots[sym][0]
            matched_qty = min(remaining, lot["qty"])

            entry_dt = datetime.fromisoformat(lot["timestamp"])
            exit_dt = datetime.fromisoformat(r["filled_at"])
            holding_minutes = (exit_dt - entry_dt).total_seconds() / 60.0

            pnl = (price - lot["price"]) * matched_qty
            pnl_pct = ((price - lot["price"]) / lot["price"] * 100.0) if lot["price"] else None

            outcomes.append({
                "source": "alpaca_order_export",
                "symbol": sym,
                "entry_timestamp": lot["timestamp"],
                "exit_timestamp": r["filled_at"],
                "holding_minutes": holding_minutes,
                "qty": matched_qty,
                "entry_price": lot["price"],
                "exit_price": price,
                "realized_pnl": pnl,
                "realized_pnl_pct": pnl_pct,
                "exit_type": r["order_type"],
                "raw_json": str({
                    "entry": lot["raw"],
                    "exit": r,
                }),
            })

            lot["qty"] -= matched_qty
            remaining -= matched_qty

            if lot["qty"] <= 1e-9:
                lots[sym].popleft()

    return outcomes


def insert_outcomes(outcomes):
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    inserted = 0

    with get_connection(DB_PATH) as con:
        for o in outcomes:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO historical_trade_outcomes (
                    source, symbol, entry_timestamp, exit_timestamp, holding_minutes,
                    qty, entry_price, exit_price, realized_pnl, realized_pnl_pct,
                    exit_type, raw_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    o["source"],
                    o["symbol"],
                    o["entry_timestamp"],
                    o["exit_timestamp"],
                    o["holding_minutes"],
                    o["qty"],
                    o["entry_price"],
                    o["exit_price"],
                    o["realized_pnl"],
                    o["realized_pnl_pct"],
                    o["exit_type"],
                    o["raw_json"],
                    now,
                ),
            )
            inserted += cur.rowcount

    return inserted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    text = Path(args.input).read_text()
    rows = split_rows(text)
    outcomes = build_outcomes_from_orders(rows)

    print()
    print("=== Alpaca order history import ===")
    print(f"  Input        : {args.input}")
    print(f"  Parsed rows  : {len(rows)}")
    print(f"  Filled rows  : {sum(1 for r in rows if r['status'] == 'filled')}")
    print(f"  Outcomes     : {len(outcomes)}")
    print(f"  Dry run      : {args.dry_run}")

    print()
    print(f"  {'Symbol':<7} {'Entry':<19} {'Exit':<19} {'Qty':>6} {'EntryPx':>10} {'ExitPx':>10} {'P&L':>10} {'P&L%':>8} {'ExitType':<10}")
    print(f"  {'-'*7} {'-'*19} {'-'*19} {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*10}")

    for o in outcomes[:40]:
        print(
            f"  {o['symbol']:<7} "
            f"{o['entry_timestamp']:<19} "
            f"{o['exit_timestamp']:<19} "
            f"{o['qty']:>6.2f} "
            f"{o['entry_price']:>10.2f} "
            f"{o['exit_price']:>10.2f} "
            f"{o['realized_pnl']:>10.2f} "
            f"{o['realized_pnl_pct']:>8.2f} "
            f"{o['exit_type']:<10}"
        )

    if len(outcomes) > 40:
        print(f"  ... {len(outcomes) - 40} more outcomes")

    if args.dry_run:
        return 0

    init_tables()
    inserted_orders = insert_orders(rows)
    inserted_outcomes = insert_outcomes(outcomes)

    print()
    print(f"Inserted external_alpaca_orders     : {inserted_orders}")
    print(f"Inserted historical_trade_outcomes  : {inserted_outcomes}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
