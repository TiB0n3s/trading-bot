#!/usr/bin/env python3
"""
Build deduplicated historical signal events from raw imported signal log rows.

Input:
- historical_signal_experience

Output:
- historical_signal_events

Purpose:
The raw journal import contains multiple rows per real signal:
- signal_received
- processing_signal
- order_placed
- rejection_or_gate

This script condenses those into one row per approximate real signal window.

Learning-only:
- Does not touch trades
- Does not touch matched_trades
- Does not affect live trading

Usage:
  python3 signal_event_builder.py --start-date 2026-05-18 --end-date 2026-05-22 --dry-run
  python3 signal_event_builder.py --start-date 2026-05-18 --end-date 2026-05-22 --replace
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta

from db import DB_PATH, get_connection


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def init_table():
    with get_connection(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS historical_signal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                market_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,

                first_timestamp TEXT,
                last_timestamp TEXT,
                signal_price REAL,
                signal_source TEXT,

                raw_signal_count INTEGER NOT NULL DEFAULT 0,
                has_signal_received INTEGER NOT NULL DEFAULT 0,
                has_processing_signal INTEGER NOT NULL DEFAULT 0,
                has_order_placed INTEGER NOT NULL DEFAULT 0,
                has_rejection_or_gate INTEGER NOT NULL DEFAULT 0,

                approved INTEGER,
                order_id TEXT,
                rejection_reason TEXT,
                decision_summary TEXT,

                raw_ids_json TEXT,
                raw_json TEXT,
                created_at TEXT NOT NULL,

                UNIQUE(market_date, symbol, action, first_timestamp, signal_price)
            )
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_historical_signal_events_date_symbol
            ON historical_signal_events(market_date, symbol)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_historical_signal_events_symbol_time
            ON historical_signal_events(symbol, first_timestamp)
        """)


def load_raw_rows(start_date=None, end_date=None, symbol=None):
    where = [
        "market_date IS NOT NULL",
        "symbol IS NOT NULL",
        "action IS NOT NULL",
        "timestamp IS NOT NULL",
        "decision_summary IN ('signal_received', 'processing_signal', 'order_placed', 'rejection_or_gate')",
    ]
    params = []

    if start_date:
        where.append("market_date >= ?")
        params.append(start_date)

    if end_date:
        where.append("market_date <= ?")
        params.append(end_date)

    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())

    with get_connection(DB_PATH) as con:
        rows = con.execute(
            f"""
            SELECT *
            FROM historical_signal_experience
            WHERE {' AND '.join(where)}
            ORDER BY market_date, symbol, action, timestamp, id
            """,
            params,
        ).fetchall()

    return rows


def should_start_new_event(current, row, window_seconds):
    if not current:
        return True

    cur_ts = parse_dt(current["last_timestamp"])
    row_ts = parse_dt(row["timestamp"])

    if not cur_ts or not row_ts:
        return True

    if row["market_date"] != current["market_date"]:
        return True
    if row["symbol"] != current["symbol"]:
        return True
    if row["action"] != current["action"]:
        return True

    return (row_ts - cur_ts).total_seconds() > window_seconds


def blank_event(row):
    return {
        "market_date": row["market_date"],
        "symbol": row["symbol"],
        "action": row["action"],
        "first_timestamp": row["timestamp"],
        "last_timestamp": row["timestamp"],
        "signal_price": row["signal_price"],
        "signal_source": row["signal_source"],
        "raw_signal_count": 0,
        "has_signal_received": 0,
        "has_processing_signal": 0,
        "has_order_placed": 0,
        "has_rejection_or_gate": 0,
        "approved": None,
        "order_id": None,
        "rejection_reason": None,
        "decision_summary": None,
        "raw_ids": [],
        "raw_rows": [],
    }


def apply_row(event, row):
    event["last_timestamp"] = row["timestamp"]
    event["raw_signal_count"] += 1
    event["raw_ids"].append(row["id"])

    # Keep compact raw row metadata for audit/debug.
    event["raw_rows"].append({
        "id": row["id"],
        "timestamp": row["timestamp"],
        "decision_summary": row["decision_summary"],
        "approved": row["approved"],
        "order_id": row["order_id"],
        "signal_price": row["signal_price"],
        "rejection_reason": row["rejection_reason"],
    })

    if row["signal_price"] is not None and event["signal_price"] is None:
        event["signal_price"] = row["signal_price"]

    if row["signal_source"] and not event["signal_source"]:
        event["signal_source"] = row["signal_source"]

    ds = row["decision_summary"]

    if ds == "signal_received":
        event["has_signal_received"] = 1
    elif ds == "processing_signal":
        event["has_processing_signal"] = 1
    elif ds == "order_placed":
        event["has_order_placed"] = 1
        event["approved"] = 1
        if row["order_id"]:
            event["order_id"] = row["order_id"]
    elif ds == "rejection_or_gate":
        event["has_rejection_or_gate"] = 1
        # Don't overwrite approval if we saw an order placed.
        if event["approved"] is None:
            event["approved"] = 0
        if row["rejection_reason"] and not event["rejection_reason"]:
            event["rejection_reason"] = row["rejection_reason"]

    # Final decision priority.
    if event["has_order_placed"]:
        event["decision_summary"] = "order_placed"
        event["approved"] = 1
    elif event["has_rejection_or_gate"]:
        event["decision_summary"] = "rejection_or_gate"
        if event["approved"] is None:
            event["approved"] = 0
    elif event["has_processing_signal"]:
        event["decision_summary"] = "processing_signal"
    elif event["has_signal_received"]:
        event["decision_summary"] = "signal_received"

    return event


def build_events(rows, window_seconds=20):
    events = []
    current = None

    for row in rows:
        if should_start_new_event(current, row, window_seconds):
            if current:
                events.append(current)
            current = blank_event(row)

        apply_row(current, row)

    if current:
        events.append(current)

    return events


def insert_events(events, replace=False):
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    inserted = 0

    with get_connection(DB_PATH) as con:
        if replace:
            con.execute("DELETE FROM historical_signal_events")

        for e in events:
            cur = con.execute(
                """
                INSERT OR REPLACE INTO historical_signal_events (
                    market_date, symbol, action,
                    first_timestamp, last_timestamp, signal_price, signal_source,
                    raw_signal_count, has_signal_received, has_processing_signal,
                    has_order_placed, has_rejection_or_gate,
                    approved, order_id, rejection_reason, decision_summary,
                    raw_ids_json, raw_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    e["market_date"],
                    e["symbol"],
                    e["action"],
                    e["first_timestamp"],
                    e["last_timestamp"],
                    e["signal_price"],
                    e["signal_source"],
                    e["raw_signal_count"],
                    e["has_signal_received"],
                    e["has_processing_signal"],
                    e["has_order_placed"],
                    e["has_rejection_or_gate"],
                    e["approved"],
                    e["order_id"],
                    e["rejection_reason"],
                    e["decision_summary"],
                    json.dumps(e["raw_ids"]),
                    json.dumps(e["raw_rows"], sort_keys=True),
                    now,
                ),
            )
            inserted += cur.rowcount

    return inserted


def print_preview(events):
    print()
    print(f"  {'Date':<10} {'Sym':<7} {'Act':<5} {'First':<19} {'Last':<19} {'Cnt':>4} {'Appr':>5} {'Decision':<18} {'Price':>10}")
    print(f"  {'-'*10} {'-'*7} {'-'*5} {'-'*19} {'-'*19} {'-'*4} {'-'*5} {'-'*18} {'-'*10}")

    for e in events[:80]:
        price = "-" if e["signal_price"] is None else f"{float(e['signal_price']):.2f}"
        appr = "-" if e["approved"] is None else str(e["approved"])
        print(
            f"  {e['market_date']:<10} "
            f"{e['symbol']:<7} "
            f"{e['action']:<5} "
            f"{e['first_timestamp']:<19} "
            f"{e['last_timestamp']:<19} "
            f"{e['raw_signal_count']:>4} "
            f"{appr:>5} "
            f"{str(e['decision_summary'] or '-'):<18} "
            f"{price:>10}"
        )

    if len(events) > 80:
        print(f"  ... {len(events) - 80} more events")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--symbol")
    parser.add_argument("--window-seconds", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    init_table()

    rows = load_raw_rows(args.start_date, args.end_date, args.symbol)
    events = build_events(rows, window_seconds=args.window_seconds)

    print()
    print("=== Historical signal event builder ===")
    print(f"  Raw rows       : {len(rows)}")
    print(f"  Signal events  : {len(events)}")
    print(f"  Window seconds : {args.window_seconds}")
    print(f"  Dry run        : {args.dry_run}")
    print(f"  Replace        : {args.replace}")

    by_decision = defaultdict(int)
    for e in events:
        by_decision[e["decision_summary"] or "unknown"] += 1
    print(f"  Decisions      : {dict(by_decision)}")

    print_preview(events)

    if args.dry_run:
        return 0

    inserted = insert_events(events, replace=args.replace)
    print()
    print(f"Inserted/updated historical_signal_events rows: {inserted}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
