#!/usr/bin/env python3
"""
Bot event audit logging.

Structured DB-backed timeline of important bot decisions:
- intelligence context
- decision policy
- portfolio replacement
- position manager
- order submissions
- learning/report runs

This is intentionally lightweight and fail-open. Event logging should never
break trading execution.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import pytz

from db import DB_PATH, get_connection


ET = pytz.timezone("America/New_York")


def now_s():
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")


def init_bot_events_table():
    with get_connection(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS bot_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                symbol TEXT,
                action TEXT,
                decision TEXT,
                severity TEXT,
                reason TEXT,
                source TEXT,
                payload_json TEXT
            )
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_bot_events_timestamp
            ON bot_events(timestamp)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_bot_events_type_symbol
            ON bot_events(event_type, symbol)
        """)


def log_event(
    event_type,
    symbol=None,
    action=None,
    decision=None,
    severity=None,
    reason=None,
    source=None,
    payload=None,
):
    """Insert one event into bot_events. Fail-open."""
    try:
        init_bot_events_table()

        payload_json = None
        if payload is not None:
            try:
                payload_json = json.dumps(payload, sort_keys=True, default=str)
            except Exception:
                payload_json = json.dumps({"unserializable_payload": str(payload)})

        with get_connection(DB_PATH) as con:
            con.execute("""
                INSERT INTO bot_events (
                    timestamp,
                    event_type,
                    symbol,
                    action,
                    decision,
                    severity,
                    reason,
                    source,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now_s(),
                event_type,
                symbol,
                action,
                decision,
                severity,
                reason,
                source,
                payload_json,
            ))

        return True

    except Exception:
        return False


def fetch_events(limit=50, event_type=None, symbol=None, since=None):
    init_bot_events_table()

    params = []
    where = ["1=1"]

    if event_type:
        where.append("event_type = ?")
        params.append(event_type)

    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())

    if since:
        where.append("timestamp >= ?")
        params.append(since)

    params.append(limit)

    with get_connection(DB_PATH) as con:
        return con.execute(f"""
            SELECT
                id,
                timestamp,
                event_type,
                symbol,
                action,
                decision,
                severity,
                reason,
                source,
                payload_json
            FROM bot_events
            WHERE {' AND '.join(where)}
            ORDER BY id DESC
            LIMIT ?
        """, params).fetchall()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="Initialize bot_events table")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--event-type")
    parser.add_argument("--symbol")
    parser.add_argument("--since", help="YYYY-MM-DD or timestamp lower bound")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init:
        init_bot_events_table()
        print("bot_events table initialized.")
        return

    rows = fetch_events(
        limit=args.limit,
        event_type=args.event_type,
        symbol=args.symbol,
        since=args.since,
    )

    if args.json:
        out = []
        for r in rows:
            item = dict(r)
            try:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            except Exception:
                item["payload"] = item.pop("payload_json")
            out.append(item)
        print(json.dumps(out, indent=2, sort_keys=True))
        return

    print("=" * 110)
    print("  Bot Events")
    print("=" * 110)
    print(f"{'ID':>6} {'Timestamp':<19} {'Type':<26} {'Sym':<6} {'Act':<6} {'Decision':<18} {'Severity':<8} Reason")
    print("-" * 140)

    for r in rows:
        print(
            f"{r['id']:>6} "
            f"{r['timestamp']:<19} "
            f"{str(r['event_type'] or ''):<26} "
            f"{str(r['symbol'] or ''):<6} "
            f"{str(r['action'] or ''):<6} "
            f"{str(r['decision'] or ''):<18} "
            f"{str(r['severity'] or ''):<8} "
            f"{str(r['reason'] or '')[:80]}"
        )


if __name__ == "__main__":
    main()
