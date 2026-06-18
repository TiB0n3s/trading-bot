"""Read-only row-count helpers for audit-write reconciliation.

Keeps direct SQLite access inside the persistence layer so the ops-check
command can stay on the approved side of the DB boundary.  These counts are the
"rows that actually landed" half of the expected-vs-written reconciliation in
:mod:`trading_bot.services.audit_write_integrity`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from db import DB_PATH, get_read_connection

# stream key -> (table, date_column, optional extra WHERE clause).
# Stream keys mirror the STREAM_* constants in
# trading_bot.services.audit_write_integrity.
WRITTEN_COUNT_SOURCES: dict[str, tuple[str, str, str | None]] = {
    "auto_buy_snapshot": ("auto_buy_candidates", "timestamp", None),
    "candidate_universe": ("candidate_universe", "candidate_ts", None),
    "intraday_feedback": ("auto_buy_intraday_feedback", "created_at", None),
    "bot_event": ("bot_events", "timestamp", "event_type = 'AUTO_BUY_CANDIDATE'"),
}


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def written_counts_for_date(target_date: str, db_path: Path | str = DB_PATH) -> dict[str, int]:
    """Return rows-written per stream for ``target_date``.

    Missing tables and per-stream query errors are skipped rather than raised so
    the diagnostic still returns partial results on a degraded database.
    """
    counts: dict[str, int] = {}
    path = Path(db_path)
    if not path.exists():
        return counts
    try:
        with get_read_connection(path) as con:
            for stream, (table, date_col, extra) in WRITTEN_COUNT_SOURCES.items():
                if not _table_exists(con, table):
                    continue
                where = [f"substr({date_col}, 1, 10) = ?"]
                if extra:
                    where.append(extra)
                sql = f"SELECT COUNT(*) FROM {table} WHERE {' AND '.join(where)}"
                try:
                    row = con.execute(sql, (target_date,)).fetchone()
                except sqlite3.Error:
                    continue
                counts[stream] = int((row[0] if row else 0) or 0)
    except sqlite3.Error:
        return counts
    return counts
