#!/usr/bin/env python3
"""Small idempotent SQLite migration runner.

This is the first migration-management foothold. It keeps schema changes
auditable without replacing the existing runtime-safe CREATE IF NOT EXISTS
initializers yet.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from db import DB_PATH, get_connection


@dataclass(frozen=True)
class Migration:
    migration_id: str
    description: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        migration_id="20260525_001_feature_snapshot_audit_fields",
        description="Add feature availability/staleness audit columns to feature_snapshots.",
        statements=(
            "ALTER TABLE feature_snapshots ADD COLUMN feature_available_at TEXT",
            "ALTER TABLE feature_snapshots ADD COLUMN feature_generated_at TEXT",
            "ALTER TABLE feature_snapshots ADD COLUMN feature_age_seconds REAL",
            "ALTER TABLE feature_snapshots ADD COLUMN source TEXT",
            "ALTER TABLE feature_snapshots ADD COLUMN is_stale INTEGER",
            "ALTER TABLE feature_snapshots ADD COLUMN staleness_reason TEXT",
        ),
    ),
    Migration(
        migration_id="20260525_002_rejected_signal_outcomes",
        description="Create canonical rejected_signal_outcomes table for counterfactual labels.",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS rejected_signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER UNIQUE,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                signal_price REAL,
                rejection_reason TEXT,
                return_5m REAL,
                return_15m REAL,
                return_30m REAL,
                return_60m REAL,
                return_eod REAL,
                max_favorable_60m REAL,
                max_adverse_60m REAL,
                label_status TEXT NOT NULL DEFAULT 'pending',
                source TEXT,
                generated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rejected_signal_outcomes_symbol_timestamp
            ON rejected_signal_outcomes(symbol, timestamp)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rejected_signal_outcomes_status
            ON rejected_signal_outcomes(label_status)
            """,
        ),
    ),
)


def ensure_migration_table(db_path: Path | str = DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now')),
                description TEXT
            )
            """
        )


def applied_migrations(db_path: Path | str = DB_PATH) -> set[str]:
    ensure_migration_table(db_path)
    with get_connection(db_path) as con:
        rows = con.execute("SELECT migration_id FROM schema_migrations").fetchall()
    return {row["migration_id"] for row in rows}


def table_columns(con, table: str) -> set[str]:
    return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def apply_migration(migration: Migration, db_path: Path | str = DB_PATH) -> bool:
    """Apply one migration if it is not already recorded."""
    ensure_migration_table(db_path)
    already_applied = applied_migrations(db_path)
    if migration.migration_id in already_applied:
        return False

    with get_connection(db_path) as con:
        for statement in migration.statements:
            if "ALTER TABLE feature_snapshots ADD COLUMN" in statement:
                columns = table_columns(con, "feature_snapshots")
                column = statement.rsplit(" ADD COLUMN ", 1)[-1].split()[0]
                if column in columns:
                    continue
            con.execute(statement)
        con.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (migration_id, description)
            VALUES (?, ?)
            """,
            (migration.migration_id, migration.description),
        )
    return True


def status(db_path: Path | str = DB_PATH) -> list[dict[str, str | bool]]:
    applied = applied_migrations(db_path)
    return [
        {
            "migration_id": migration.migration_id,
            "description": migration.description,
            "applied": migration.migration_id in applied,
        }
        for migration in MIGRATIONS
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "apply"))
    parser.add_argument("--db-path", default=str(DB_PATH))
    args = parser.parse_args()

    if args.command == "status":
        print("=== DB migration status ===")
        for item in status(args.db_path):
            marker = "applied" if item["applied"] else "pending"
            print(f"{marker:>8}  {item['migration_id']}  {item['description']}")
        return 0

    applied_count = 0
    for migration in MIGRATIONS:
        if apply_migration(migration, args.db_path):
            applied_count += 1
            print(f"[APPLIED] {migration.migration_id}")
        else:
            print(f"[SKIP]    {migration.migration_id}")
    print(f"applied_count={applied_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
