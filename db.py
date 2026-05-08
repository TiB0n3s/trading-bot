#!/usr/bin/env python3
"""
Shared SQLite helpers for the trading bot.

Goals:
- Consistent row_factory
- WAL mode for better concurrent read/write behavior
- busy_timeout to reduce transient lock failures
- Centralized schema/index maintenance
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "trades.db"

BUSY_TIMEOUT_MS = 5000


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Return a configured SQLite connection.

    Use this helper instead of raw sqlite3.connect() for app/reporting code.
    """
    con = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    con.row_factory = sqlite3.Row

    # WAL improves concurrent reads while app/fill_stream write.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA foreign_keys=ON")

    return con


def init_db_performance_indexes(db_path: Path | str = DB_PATH) -> None:
    """Create useful indexes for webhook checks, reports, and reconciliation.

    Safe/idempotent: CREATE INDEX IF NOT EXISTS.
    """
    with get_connection(db_path) as con:
        con.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id)")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_approved_status_timestamp "
            "ON trades(approved, order_status, timestamp)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_symbol_action_timestamp "
            "ON trades(symbol, action, timestamp)"
        )

        # These tables may not exist in very old DBs, so guard them.
        existing = {
            row["name"]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "recent_webhooks" in existing:
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_recent_webhooks_first_seen "
                "ON recent_webhooks(first_seen)"
            )

        if "fill_events" in existing:
            con.execute("CREATE INDEX IF NOT EXISTS idx_fill_events_timestamp ON fill_events(timestamp)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_fill_events_order_id ON fill_events(order_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_fill_events_symbol_timestamp ON fill_events(symbol, timestamp)")


def db_health_summary(db_path: Path | str = DB_PATH) -> dict:
    """Return a small DB health summary for smoke checks."""
    with get_connection(db_path) as con:
        tables = [
            row["name"]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]

        indexes = [
            row["name"]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
            ).fetchall()
        ]

        journal_mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = con.execute("PRAGMA busy_timeout").fetchone()[0]

    return {
        "db_path": str(db_path),
        "journal_mode": journal_mode,
        "busy_timeout_ms": busy_timeout,
        "tables": tables,
        "indexes": indexes,
    }


def main() -> int:
    init_db_performance_indexes()
    summary = db_health_summary()

    print("DB health summary")
    print("-----------------")
    print("db_path        :", summary["db_path"])
    print("journal_mode   :", summary["journal_mode"])
    print("busy_timeout_ms:", summary["busy_timeout_ms"])
    print("tables         :", ", ".join(summary["tables"]))
    print("indexes        :")
    for idx in summary["indexes"]:
        print("  -", idx)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
