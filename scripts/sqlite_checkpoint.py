#!/usr/bin/env python3
"""Bounded SQLite WAL maintenance for operator/cron use."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "trades.db"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument(
        "--mode",
        default="TRUNCATE",
        choices=("PASSIVE", "FULL", "RESTART", "TRUNCATE"),
        help="SQLite wal_checkpoint mode.",
    )
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--wal-autocheckpoint", type=int, default=1000)
    parser.add_argument("--journal-size-limit", type=int, default=67108864)
    parser.add_argument(
        "--set-wal",
        action="store_true",
        help="Set journal_mode=WAL before checkpointing.",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def run_checkpoint(
    db_path: Path,
    *,
    mode: str,
    busy_timeout_ms: int,
    wal_autocheckpoint: int,
    journal_size_limit: int,
    set_wal: bool,
) -> dict[str, object]:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    with sqlite3.connect(db_path, timeout=max(busy_timeout_ms, 0) / 1000) as con:
        con.row_factory = sqlite3.Row
        con.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        journal_mode = None
        if set_wal:
            journal_mode = con.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute(f"PRAGMA wal_autocheckpoint={wal_autocheckpoint}")
        con.execute(f"PRAGMA journal_size_limit={journal_size_limit}")
        checkpoint_row = con.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        con.execute("PRAGMA optimize")

    wal_path = db_path.with_name(db_path.name + "-wal")
    shm_path = db_path.with_name(db_path.name + "-shm")
    return {
        "db_path": str(db_path),
        "journal_mode": journal_mode,
        "checkpoint_mode": mode,
        "busy": checkpoint_row[0] if checkpoint_row else None,
        "log_frames": checkpoint_row[1] if checkpoint_row else None,
        "checkpointed_frames": checkpoint_row[2] if checkpoint_row else None,
        "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
        "shm_bytes": shm_path.stat().st_size if shm_path.exists() else 0,
    }


def main() -> int:
    args = _parse_args()
    result = run_checkpoint(
        Path(args.db_path),
        mode=args.mode,
        busy_timeout_ms=args.busy_timeout_ms,
        wal_autocheckpoint=args.wal_autocheckpoint,
        journal_size_limit=args.journal_size_limit,
        set_wal=args.set_wal,
    )
    if not args.quiet:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
