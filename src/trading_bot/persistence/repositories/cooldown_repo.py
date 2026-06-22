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


def _cooldown_active(existing_iso: str, now_iso: str, window_seconds: int) -> bool:
    """True if an existing cooldown timestamp is still inside the active window.

    Fail closed: if either timestamp cannot be parsed, treat the cooldown as
    active so we never double-submit on bad data.
    """
    try:
        existing = datetime.fromisoformat(existing_iso)
        now = datetime.fromisoformat(now_iso)
        return (now - existing).total_seconds() < window_seconds
    except Exception:
        return True


def claim_cooldown(
    symbol: str,
    action: str,
    now_iso: str,
    window_seconds: int,
    db_path=DB_PATH,
) -> tuple[bool, str | None]:
    """Atomically reserve the (symbol, action) cooldown slot.

    This is cross-PROCESS admission control: gunicorn runs multiple worker
    processes, each with its own signal thread pool, so an in-process lock is
    insufficient. ``BEGIN IMMEDIATE`` takes a write lock for the whole
    read-modify-write, serializing concurrent claimants across processes.

    Returns ``(claimed, active_last_order_time)``:
      * ``(True, prior_or_None)``  -> caller owns the cooldown (last_order_time
        is now ``now_iso``); ``prior`` is the previous (expired/None) value, for
        optional restore on release. The caller MUST ``release_cooldown`` if it
        does not actually submit an order.
      * ``(False, existing)`` -> an active cooldown already exists; the caller
        MUST NOT submit.
    """
    con = get_connection(db_path)
    try:
        con.isolation_level = None  # explicit transaction control
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT last_order_time FROM cooldowns WHERE symbol = ? AND action = ?",
            (symbol, action),
        ).fetchone()
        prior = row[0] if row is not None else None
        if prior is not None and _cooldown_active(prior, now_iso, window_seconds):
            con.execute("ROLLBACK")
            return False, prior
        con.execute(
            "INSERT OR REPLACE INTO cooldowns (symbol, action, last_order_time) VALUES (?, ?, ?)",
            (symbol, action, now_iso),
        )
        con.execute("COMMIT")
        return True, prior
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()


def release_cooldown(
    symbol: str,
    action: str,
    restore_iso: str | None = None,
    db_path=DB_PATH,
) -> None:
    """Undo a ``claim_cooldown`` reservation when no order was submitted.

    Only call after ``claim_cooldown`` returned ``claimed=True`` and the order
    was NOT placed. If ``restore_iso`` is given (the prior timestamp) it is
    written back; otherwise the row is deleted so a legitimate retry is allowed
    immediately. (On a successful claim the prior value was already expired or
    absent, so deleting is the normal release.)
    """
    with get_connection(db_path) as con:
        if restore_iso:
            con.execute(
                "INSERT OR REPLACE INTO cooldowns (symbol, action, last_order_time) VALUES (?, ?, ?)",
                (symbol, action, restore_iso),
            )
        else:
            con.execute(
                "DELETE FROM cooldowns WHERE symbol = ? AND action = ?",
                (symbol, action),
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
