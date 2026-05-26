#!/usr/bin/env python3
"""Tests for idempotent DB migration runner."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db_migrations import MIGRATIONS, apply_migration, status


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def make_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE feature_snapshots (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                symbol TEXT
            )
            """
        )


def columns(path: Path) -> set[str]:
    with sqlite3.connect(path) as con:
        rows = con.execute("PRAGMA table_info(feature_snapshots)").fetchall()
    return {row[1] for row in rows}


def table_columns(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as con:
        rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def test_feature_audit_migration_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        make_db(db_path)
        first_status = status(db_path)
        assert_equal(first_status[0]["applied"], False, "initial status")

        applied = apply_migration(MIGRATIONS[0], db_path)
        assert_equal(applied, True, "first apply")

        expected = {
            "feature_available_at",
            "feature_generated_at",
            "feature_age_seconds",
            "source",
            "is_stale",
            "staleness_reason",
        }
        assert_true(expected <= columns(db_path), "audit columns")

        applied_again = apply_migration(MIGRATIONS[0], db_path)
        assert_equal(applied_again, False, "second apply")
        assert_equal(status(db_path)[0]["applied"], True, "final status")


def test_rejected_signal_outcomes_migration_creates_table():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        make_db(db_path)
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")

        applied = apply_migration(MIGRATIONS[1], db_path)
        assert_equal(applied, True, "apply")

        with sqlite3.connect(db_path) as con:
            row = con.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'rejected_signal_outcomes'
                """
            ).fetchone()
        assert_true(row is not None, "rejected_signal_outcomes table")


def test_webhook_event_status_migration_adds_columns():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE webhook_events (
                    dedupe_key TEXT PRIMARY KEY,
                    received_at TEXT,
                    status TEXT
                )
                """
            )

        applied = apply_migration(MIGRATIONS[2], db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "queued_at",
            "started_at",
            "finished_at",
            "order_id",
            "client_order_id",
            "failure_reason",
        }
        assert_true(expected <= table_columns(db_path, "webhook_events"), "webhook event status columns")


def test_trade_decision_context_migration_adds_columns():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    symbol TEXT,
                    action TEXT
                )
                """
            )

        applied = apply_migration(MIGRATIONS[3], db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "macro_regime",
            "market_bias",
            "prediction_decision",
            "setup_policy_action",
            "buy_opportunity_score",
            "buy_opportunity_reason",
        }
        assert_true(expected <= table_columns(db_path, "trades"), "trade decision context columns")


def test_decision_snapshots_migration_creates_table():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")

        applied = apply_migration(MIGRATIONS[4], db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "decision_time",
            "trade_id",
            "source",
            "final_decision",
            "market_context_hash",
            "symbol_universe_version",
            "env_profile_hash",
            "git_sha",
        }
        assert_true(expected <= table_columns(db_path, "decision_snapshots"), "decision snapshot columns")


if __name__ == "__main__":
    test_feature_audit_migration_is_idempotent()
    print("[OK] test_feature_audit_migration_is_idempotent")
    test_rejected_signal_outcomes_migration_creates_table()
    print("[OK] test_rejected_signal_outcomes_migration_creates_table")
    test_webhook_event_status_migration_adds_columns()
    print("[OK] test_webhook_event_status_migration_adds_columns")
    test_trade_decision_context_migration_adds_columns()
    print("[OK] test_trade_decision_context_migration_adds_columns")
    test_decision_snapshots_migration_creates_table()
    print("[OK] test_decision_snapshots_migration_creates_table")
    print("\nAll 5 DB migration tests passed.")
