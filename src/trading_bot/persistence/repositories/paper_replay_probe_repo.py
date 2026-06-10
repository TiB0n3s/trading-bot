"""Repository helpers for diagnostic paper replay/load probes."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def init_probe_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_replay_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_replay_fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_dedupe_key TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                fill_price REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )


def record_signal_and_fill(
    db_path: Path,
    *,
    dedupe_key: str,
    symbol: str,
    action: str,
    price: float,
    status: str = "queued",
) -> None:
    created_at = time.time()
    with sqlite3.connect(db_path, timeout=30) as con:
        con.execute(
            """
            INSERT INTO paper_replay_signals
                (dedupe_key, symbol, action, price, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (dedupe_key, symbol, action, price, status, created_at),
        )
        con.execute(
            """
            INSERT INTO paper_replay_fills
                (signal_dedupe_key, symbol, action, fill_price, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (dedupe_key, symbol, action, price, created_at),
        )


def count_rows(db_path: Path, table: str) -> int:
    if table not in {"paper_replay_signals", "paper_replay_fills"}:
        raise ValueError(f"unsupported paper replay probe table: {table}")
    with sqlite3.connect(db_path) as con:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
