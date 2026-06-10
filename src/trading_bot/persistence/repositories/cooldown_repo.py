"""Repository for cooldown, recent-sell, and webhook dedupe state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

import pytz
from db import DB_PATH, get_connection


def recent_webhook_seen(
    dedupe_key: str,
    symbol: str,
    action: str,
    price: Any,
    dedupe_seconds: int,
    db_path=DB_PATH,
) -> bool:
    et = pytz.timezone("America/New_York")
    now_et = datetime.now(et)
    cutoff = now_et - timedelta(seconds=dedupe_seconds)
    with get_connection(db_path) as con:
        con.execute(
            "DELETE FROM recent_webhooks WHERE first_seen < ?",
            (cutoff.isoformat(),),
        )
        row = con.execute(
            "SELECT first_seen FROM recent_webhooks WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()
        if row:
            return True
        con.execute(
            "INSERT OR REPLACE INTO recent_webhooks "
            "(dedupe_key, symbol, action, signal_price, first_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (dedupe_key, symbol, action, float(price), now_et.isoformat()),
        )
    return False


def cooldown_rows(db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute("SELECT symbol, action, last_order_time FROM cooldowns").fetchall()


def recent_sell_rows(db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            "SELECT symbol, last_sell_time, last_sell_price FROM recent_sells"
        ).fetchall()


def read_cooldown(symbol: str, action: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            "SELECT last_order_time FROM cooldowns WHERE symbol = ? AND action = ?",
            (symbol, action),
        ).fetchone()


def read_recent_sell(symbol: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            "SELECT last_sell_time, last_sell_price FROM recent_sells WHERE symbol = ?",
            (symbol,),
        ).fetchone()


def write_cooldown(symbol: str, action: str, timestamp: str, db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            "INSERT OR REPLACE INTO cooldowns (symbol, action, last_order_time) VALUES (?, ?, ?)",
            (symbol, action, timestamp),
        )


def write_recent_sell(symbol: str, timestamp: str, price: float, db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            "INSERT OR REPLACE INTO recent_sells (symbol, last_sell_time, last_sell_price) VALUES (?, ?, ?)",
            (symbol, timestamp, price),
        )


def record_webhook_event(dedupe_key: str, data: dict, dedupe_seconds: int, db_path=DB_PATH) -> bool:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_connection(db_path) as con:
            con.execute(
                """
                DELETE FROM webhook_events
                WHERE received_at < datetime('now', ?)
                """,
                (f"-{dedupe_seconds} seconds",),
            )
            con.execute(
                """
                INSERT INTO webhook_events (
                    dedupe_key, received_at, symbol, action, signal_price, source,
                    payload_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'received')
                """,
                (
                    dedupe_key,
                    timestamp,
                    str(data.get("symbol", "")).upper(),
                    str(data.get("action", "")).lower(),
                    data.get("price"),
                    data.get("source"),
                    json.dumps(data, sort_keys=True),
                ),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def mark_webhook_event_status(
    dedupe_key: str,
    status: str,
    order_id: str | None = None,
    client_order_id: str | None = None,
    failure_reason: str | None = None,
    db_path=DB_PATH,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    time_column = None
    if status == "queued":
        time_column = "queued_at"
    elif status in ("processing", "started"):
        time_column = "started_at"
    elif status in (
        "processed",
        "rejected",
        "submitted",
        "submit_failed",
        "duplicate_ignored",
        "error",
    ):
        time_column = "finished_at"

    assignments = ["status = ?"]
    params: list[Any] = [status]
    if time_column:
        assignments.append(f"{time_column} = ?")
        params.append(now)
    if order_id is not None:
        assignments.append("order_id = ?")
        params.append(order_id)
    if client_order_id is not None:
        assignments.append("client_order_id = ?")
        params.append(client_order_id)
    if failure_reason is not None:
        assignments.append("failure_reason = ?")
        params.append(str(failure_reason)[:500])

    params.append(dedupe_key)
    with get_connection(db_path) as con:
        con.execute(
            f"UPDATE webhook_events SET {', '.join(assignments)} WHERE dedupe_key = ?",
            params,
        )
