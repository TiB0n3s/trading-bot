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


def test_rejected_outcome_partial_reason_migration_adds_column():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE rejected_signal_outcomes (
                    id INTEGER PRIMARY KEY,
                    trade_id INTEGER UNIQUE,
                    timestamp TEXT,
                    symbol TEXT,
                    action TEXT,
                    label_status TEXT
                )
                """
            )

        applied = apply_migration(MIGRATIONS[5], db_path)
        assert_equal(applied, True, "apply")
        assert_true({"partial_reason"} <= table_columns(db_path, "rejected_signal_outcomes"), "partial reason column")


def test_strong_day_participation_migration_creates_table():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        applied = apply_migration(MIGRATIONS[6], db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "market_date",
            "symbol",
            "primary_status",
            "prediction_score",
            "auto_buy_candidate_count",
            "raw_json",
        }
        assert_true(expected <= table_columns(db_path, "strong_day_participation"), "strong day participation columns")


def test_auto_buy_decision_snapshots_migration_creates_table():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        applied = apply_migration(MIGRATIONS[7], db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "candidate_timestamp",
            "symbol",
            "decision",
            "live_block_reason",
            "order_submitted",
            "candidate_json",
            "runtime_effect",
        }
        assert_true(expected <= table_columns(db_path, "auto_buy_decision_snapshots"), "auto-buy snapshot columns")


def test_historical_trend_context_migration_creates_table():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        applied = apply_migration(MIGRATIONS[8], db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "market_date",
            "symbol",
            "trend_label",
            "trend_regime",
            "trend_confidence",
            "relative_strength_score",
            "raw_json",
        }
        assert_true(expected <= table_columns(db_path, "historical_trend_context"), "historical trend columns")


def test_entry_intelligence_migration_adds_columns():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        make_db(db_path)
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")
        apply_migration(MIGRATIONS[4], db_path)

        applied = apply_migration(MIGRATIONS[9], db_path)
        assert_equal(applied, True, "apply")

        decision_expected = {
            "momentum_acceleration_pct",
            "momentum_state",
            "volume_surge_ratio",
            "volume_state",
            "extension_from_recent_base_pct",
            "prior_session_return_pct",
            "tape_label_at_signal",
            "tape_bar_age_seconds",
        }
        feature_expected = {
            "momentum_acceleration_pct",
            "volume_surge_ratio",
            "extension_from_recent_base_pct",
            "prior_session_return_pct",
        }
        assert_true(decision_expected <= table_columns(db_path, "decision_snapshots"), "entry decision columns")
        assert_true(feature_expected <= table_columns(db_path, "feature_snapshots"), "entry feature columns")


def test_decision_snapshot_feature_parity_migration_adds_columns():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")
        apply_migration(MIGRATIONS[4], db_path)

        migration = next(
            m
            for m in MIGRATIONS
            if m.migration_id == "20260531_016_decision_snapshot_feature_parity"
        )
        applied = apply_migration(migration, db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "setup_confidence",
            "prediction_confidence",
            "prediction_sample_size",
            "feature_semantic_version",
        }
        assert_true(expected <= table_columns(db_path, "decision_snapshots"), "feature parity decision columns")


def test_canonical_intelligence_migration_adds_columns():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")
        apply_migration(MIGRATIONS[4], db_path)

        migration = next(
            m
            for m in MIGRATIONS
            if m.migration_id == "20260531_017_canonical_intelligence_snapshot"
        )
        applied = apply_migration(migration, db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "canonical_intelligence_version",
            "canonical_intelligence_hash",
            "canonical_intelligence_json",
        }
        assert_true(expected <= table_columns(db_path, "decision_snapshots"), "canonical intelligence columns")


def test_canonical_exit_snapshot_migration_creates_table():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        migration = next(
            m
            for m in MIGRATIONS
            if m.migration_id == "20260531_018_canonical_exit_snapshots"
        )
        applied = apply_migration(migration, db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "exit_trade_id",
            "decision_snapshot_id",
            "entry_trade_id",
            "matched_trade_id",
            "position_id",
            "symbol",
            "exit_timestamp",
            "exit_trigger",
            "exit_source",
            "realized_pnl",
            "realized_return_pct",
            "mfe_pct",
            "capture_ratio",
            "max_adverse_excursion_pct",
            "avoided_drawdown_pct",
            "missed_upside_pct",
            "post_exit_return_30m_pct",
            "post_exit_return_60m_pct",
            "reentry_window_summary",
            "exit_regime_state_json",
            "exit_momentum_state_json",
            "exit_trend_state_json",
            "canonical_exit_version",
            "canonical_exit_hash",
            "canonical_exit_json",
            "canonical_intelligence_hash",
            "entry_canonical_intelligence_version",
            "entry_canonical_intelligence_hash",
        }
        assert_true(expected <= table_columns(db_path, "exit_snapshots"), "canonical exit snapshot columns")


def test_exit_snapshot_lifecycle_links_migration_adds_columns():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        # Simulate a database that already had the v18 table before lifecycle
        # columns were promoted into the base CREATE TABLE.
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE exit_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    exit_trade_id INTEGER,
                    matched_trade_id INTEGER,
                    symbol TEXT,
                    exit_timestamp TEXT,
                    exit_trigger TEXT,
                    exit_source TEXT,
                    realized_pnl REAL,
                    realized_return_pct REAL,
                    mfe_pct REAL,
                    capture_ratio REAL,
                    avoided_drawdown_pct REAL,
                    missed_upside_pct REAL,
                    post_exit_return_30m_pct REAL,
                    post_exit_return_60m_pct REAL,
                    canonical_exit_version TEXT NOT NULL,
                    canonical_exit_hash TEXT NOT NULL,
                    canonical_exit_json TEXT NOT NULL,
                    canonical_intelligence_hash TEXT
                )
                """
            )

        migration = next(
            m
            for m in MIGRATIONS
            if m.migration_id == "20260531_019_exit_snapshot_lifecycle_links"
        )
        applied = apply_migration(migration, db_path)
        assert_equal(applied, True, "apply")

        expected = {
            "decision_snapshot_id",
            "entry_trade_id",
            "position_id",
            "max_adverse_excursion_pct",
            "reentry_window_summary",
            "exit_regime_state_json",
            "exit_momentum_state_json",
            "exit_trend_state_json",
            "entry_canonical_intelligence_version",
            "entry_canonical_intelligence_hash",
        }
        assert_true(expected <= table_columns(db_path, "exit_snapshots"), "exit lifecycle link columns")


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
    test_rejected_outcome_partial_reason_migration_adds_column()
    print("[OK] test_rejected_outcome_partial_reason_migration_adds_column")
    test_strong_day_participation_migration_creates_table()
    print("[OK] test_strong_day_participation_migration_creates_table")
    test_auto_buy_decision_snapshots_migration_creates_table()
    print("[OK] test_auto_buy_decision_snapshots_migration_creates_table")
    test_historical_trend_context_migration_creates_table()
    print("[OK] test_historical_trend_context_migration_creates_table")
    test_entry_intelligence_migration_adds_columns()
    print("[OK] test_entry_intelligence_migration_adds_columns")
    test_decision_snapshot_feature_parity_migration_adds_columns()
    print("[OK] test_decision_snapshot_feature_parity_migration_adds_columns")
    test_canonical_intelligence_migration_adds_columns()
    print("[OK] test_canonical_intelligence_migration_adds_columns")
    test_canonical_exit_snapshot_migration_creates_table()
    print("[OK] test_canonical_exit_snapshot_migration_creates_table")
    test_exit_snapshot_lifecycle_links_migration_adds_columns()
    print("[OK] test_exit_snapshot_lifecycle_links_migration_adds_columns")
    print("\nAll 14 DB migration tests passed.")
