#!/usr/bin/env python3
"""
Trade ledger helpers.

Future home for trades.db insert/update abstractions.

This module is intentionally conservative right now:
- read-only helpers
- column introspection
- simple row counting
- no live behavior changes
"""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection


def table_exists(table_name: str, db_path=DB_PATH) -> bool:
    """Return True if a table exists in the SQLite database."""
    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()

    return row is not None


def table_columns(table_name: str, db_path=DB_PATH) -> list[str]:
    """Return column names for a table."""
    if not table_exists(table_name, db_path):
        return []

    with get_connection(db_path) as con:
        rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()

    return [r["name"] for r in rows]


def trades_columns(db_path=DB_PATH) -> list[str]:
    """Return column names for the trades table."""
    return table_columns("trades", db_path)


def count_rows(table_name: str, db_path=DB_PATH) -> int:
    """Return row count for a table, or 0 if it does not exist."""
    if not table_exists(table_name, db_path):
        return 0

    with get_connection(db_path) as con:
        row = con.execute(f"SELECT COUNT(*) AS n FROM {table_name}").fetchone()

    return int(row["n"] or 0)


def latest_trade_rows(limit: int = 10, db_path=DB_PATH) -> list[dict[str, Any]]:
    """Return recent trades rows as dictionaries."""
    limit = max(1, min(int(limit), 100))

    if not table_exists("trades", db_path):
        return []

    with get_connection(db_path) as con:
        rows = con.execute(
            """
            SELECT *
            FROM trades
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(r) for r in rows]


def ledger_summary(db_path=DB_PATH) -> dict[str, Any]:
    """Return a compact read-only summary of the trading ledger."""
    return {
        "db_path": str(db_path),
        "has_trades": table_exists("trades", db_path),
        "has_matched_trades": table_exists("matched_trades", db_path),
        "has_fill_events": table_exists("fill_events", db_path),
        "trades_count": count_rows("trades", db_path),
        "matched_trades_count": count_rows("matched_trades", db_path),
        "fill_events_count": count_rows("fill_events", db_path),
        "trades_columns": trades_columns(db_path),
    }
