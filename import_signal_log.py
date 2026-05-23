#!/usr/bin/env python3
"""
Import historical bot signal/decision log lines into learning-only tables.

This does NOT modify trades.
This does NOT modify matched_trades.
This does NOT affect live trading.

Creates:
- historical_signal_experience

Usage:
  python3 import_signal_log.py /tmp/signal_learning_export/signals_may18_22.log --dry-run
  python3 import_signal_log.py /tmp/signal_learning_export/signals_may18_22.log
"""

import argparse
import ast
import json
import re
from datetime import datetime
from pathlib import Path

from db import DB_PATH, get_connection


TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
SIGNAL_RE = re.compile(r"Signal received:\s*(\{.*\})")
PROCESS_RE = re.compile(r"Processing\s+(BUY|SELL)\s+signal\s+for\s+([A-Z]+)\s+at\s+([\d.]+)", re.I)
ORDER_RE = re.compile(r"ORDER PLACED:\s*(\{.*\})")
REJECT_RE = re.compile(r"(REJECTED|rejected|blocked|skips?|skip|Cooldown|Exposure|churn|Trend|bias|chase|confidence)", re.I)


def init_tables():
    with get_connection(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS historical_signal_experience (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                timestamp TEXT,
                market_date TEXT,
                symbol TEXT,
                action TEXT,
                signal_price REAL,
                signal_source TEXT,
                approved INTEGER,
                order_id TEXT,
                rejection_reason TEXT,
                decision_summary TEXT,
                raw_line TEXT NOT NULL,
                raw_json TEXT,
                imported_at TEXT NOT NULL,
                UNIQUE(source, timestamp, symbol, action, signal_price, raw_line)
            )
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_historical_signal_experience_date_symbol
            ON historical_signal_experience(market_date, symbol)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_historical_signal_experience_symbol_time
            ON historical_signal_experience(symbol, timestamp)
        """)


def parse_ts(line):
    m = TS_RE.search(line)
    return m.group(1) if m else None


def parse_payload(text):
    try:
        return ast.literal_eval(text)
    except Exception:
        try:
            return json.loads(text)
        except Exception:
            return None


def parse_line(line):
    ts = parse_ts(line)
    market_date = ts[:10] if ts else None

    row = {
        "source": "trading_bot_log",
        "timestamp": ts,
        "market_date": market_date,
        "symbol": None,
        "action": None,
        "signal_price": None,
        "signal_source": None,
        "approved": None,
        "order_id": None,
        "rejection_reason": None,
        "decision_summary": None,
        "raw_line": line.rstrip(),
        "raw_json": None,
    }

    # Signal received: {'action': 'buy', 'symbol': 'AAPL', 'price': 123.45, ...}
    m = SIGNAL_RE.search(line)
    if m:
        payload = parse_payload(m.group(1))
        if payload:
            row["symbol"] = str(payload.get("symbol") or "").upper() or None
            row["action"] = str(payload.get("action") or "").lower() or None
            try:
                row["signal_price"] = float(payload.get("price")) if payload.get("price") is not None else None
            except Exception:
                row["signal_price"] = None
            row["signal_source"] = payload.get("source")
            row["decision_summary"] = "signal_received"
            row["raw_json"] = json.dumps(payload, sort_keys=True)
            return row

    # Processing BUY signal for AAPL at 123.45
    m = PROCESS_RE.search(line)
    if m:
        action, symbol, price = m.groups()
        row["symbol"] = symbol.upper()
        row["action"] = action.lower()
        row["signal_price"] = float(price)
        row["decision_summary"] = "processing_signal"
        return row

    # ORDER PLACED: {'order_id': ..., 'symbol': ..., 'side': 'buy', ...}
    m = ORDER_RE.search(line)
    if m:
        payload = parse_payload(m.group(1))
        if payload:
            row["symbol"] = str(payload.get("symbol") or "").upper() or None
            row["action"] = str(payload.get("side") or payload.get("action") or "").lower() or None
            row["approved"] = 1
            row["order_id"] = payload.get("order_id")
            row["decision_summary"] = "order_placed"
            row["raw_json"] = json.dumps(payload, sort_keys=True)
            return row

    # Generic rejection / gate line. Try to infer symbol/action.
    if REJECT_RE.search(line):
        symbol = None
        action = None

        sm = re.search(r"\b([A-Z]{1,5})\b", line)
        if sm:
            candidate = sm.group(1)
            if candidate not in {"INFO", "WARN", "ERROR", "BUY", "SELL"}:
                symbol = candidate

        am = re.search(r"\b(BUY|SELL)\b", line, re.I)
        if am:
            action = am.group(1).lower()

        row["symbol"] = symbol
        row["action"] = action
        row["approved"] = 0
        row["rejection_reason"] = line.split(" - ", 2)[-1][-500:]
        row["decision_summary"] = "rejection_or_gate"
        return row

    return None


def insert_rows(rows):
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    inserted = 0

    with get_connection(DB_PATH) as con:
        for r in rows:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO historical_signal_experience (
                    source, timestamp, market_date, symbol, action, signal_price,
                    signal_source, approved, order_id, rejection_reason,
                    decision_summary, raw_line, raw_json, imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["source"],
                    r["timestamp"],
                    r["market_date"],
                    r["symbol"],
                    r["action"],
                    r["signal_price"],
                    r["signal_source"],
                    r["approved"],
                    r["order_id"],
                    r["rejection_reason"],
                    r["decision_summary"],
                    r["raw_line"],
                    r["raw_json"],
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

    lines = Path(args.input).read_text(errors="replace").splitlines()
    rows = []

    for line in lines:
        parsed = parse_line(line)
        if parsed:
            rows.append(parsed)

    print()
    print("=== Signal log import ===")
    print(f"  Input       : {args.input}")
    print(f"  Lines       : {len(lines)}")
    print(f"  Parsed rows : {len(rows)}")
    print(f"  Dry run     : {args.dry_run}")

    by_summary = {}
    for r in rows:
        by_summary[r["decision_summary"]] = by_summary.get(r["decision_summary"], 0) + 1

    print(f"  Summary     : {by_summary}")

    print()
    print(f"  {'Timestamp':<19} {'Sym':<7} {'Action':<6} {'Price':>10} {'Approved':>8} {'Type':<20} Reason")
    print(f"  {'-'*19} {'-'*7} {'-'*6} {'-'*10} {'-'*8} {'-'*20} {'-'*60}")

    for r in rows[:50]:
        price = "-" if r["signal_price"] is None else f"{r['signal_price']:.2f}"
        approved = "-" if r["approved"] is None else str(r["approved"])
        print(
            f"  {str(r['timestamp'] or '-'):<19} "
            f"{str(r['symbol'] or '-'):<7} "
            f"{str(r['action'] or '-'):<6} "
            f"{price:>10} "
            f"{approved:>8} "
            f"{str(r['decision_summary'] or '-'):<20} "
            f"{str(r['rejection_reason'] or '')[:80]}"
        )

    if len(rows) > 50:
        print(f"  ... {len(rows) - 50} more rows")

    if args.dry_run:
        return 0

    init_tables()
    inserted = insert_rows(rows)
    print()
    print(f"Inserted historical_signal_experience rows: {inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
