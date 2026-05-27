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
    Migration(
        migration_id="20260525_003_webhook_event_status_columns",
        description="Add webhook event lifecycle/status metadata columns.",
        statements=(
            "ALTER TABLE webhook_events ADD COLUMN queued_at TEXT",
            "ALTER TABLE webhook_events ADD COLUMN started_at TEXT",
            "ALTER TABLE webhook_events ADD COLUMN finished_at TEXT",
            "ALTER TABLE webhook_events ADD COLUMN order_id TEXT",
            "ALTER TABLE webhook_events ADD COLUMN client_order_id TEXT",
            "ALTER TABLE webhook_events ADD COLUMN failure_reason TEXT",
        ),
    ),
    Migration(
        migration_id="20260525_004_trade_decision_context_columns",
        description="Add decision-context attribution columns to trades.",
        statements=(
            "ALTER TABLE trades ADD COLUMN macro_regime TEXT",
            "ALTER TABLE trades ADD COLUMN risk_multiplier REAL",
            "ALTER TABLE trades ADD COLUMN market_bias TEXT",
            "ALTER TABLE trades ADD COLUMN market_bias_effective TEXT",
            "ALTER TABLE trades ADD COLUMN market_bias_override_reason TEXT",
            "ALTER TABLE trades ADD COLUMN fundamental_score TEXT",
            "ALTER TABLE trades ADD COLUMN risk_level TEXT",
            "ALTER TABLE trades ADD COLUMN entry_quality TEXT",
            "ALTER TABLE trades ADD COLUMN trend_direction TEXT",
            "ALTER TABLE trades ADD COLUMN trend_strength TEXT",
            "ALTER TABLE trades ADD COLUMN momentum_direction TEXT",
            "ALTER TABLE trades ADD COLUMN session_trend_label TEXT",
            "ALTER TABLE trades ADD COLUMN session_trend_score REAL",
            "ALTER TABLE trades ADD COLUMN session_return_pct REAL",
            "ALTER TABLE trades ADD COLUMN session_momentum_5m_pct REAL",
            "ALTER TABLE trades ADD COLUMN session_momentum_15m_pct REAL",
            "ALTER TABLE trades ADD COLUMN session_momentum_30m_pct REAL",
            "ALTER TABLE trades ADD COLUMN session_distance_from_vwap_pct REAL",
            "ALTER TABLE trades ADD COLUMN session_momentum_reason TEXT",
            "ALTER TABLE trades ADD COLUMN momentum_pct REAL",
            "ALTER TABLE trades ADD COLUMN prediction_score REAL",
            "ALTER TABLE trades ADD COLUMN prediction_decision TEXT",
            "ALTER TABLE trades ADD COLUMN prediction_reason TEXT",
            "ALTER TABLE trades ADD COLUMN correlation_cluster TEXT",
            "ALTER TABLE trades ADD COLUMN cluster_exposure_pct REAL",
            "ALTER TABLE trades ADD COLUMN setup_label TEXT",
            "ALTER TABLE trades ADD COLUMN setup_policy_action TEXT",
            "ALTER TABLE trades ADD COLUMN setup_policy_reason TEXT",
            "ALTER TABLE trades ADD COLUMN setup_confidence_adjustment REAL",
            "ALTER TABLE trades ADD COLUMN setup_size_multiplier REAL",
            "ALTER TABLE trades ADD COLUMN buy_opportunity_score REAL",
            "ALTER TABLE trades ADD COLUMN buy_opportunity_recommendation TEXT",
            "ALTER TABLE trades ADD COLUMN buy_opportunity_reason TEXT",
        ),
    ),
    Migration(
        migration_id="20260526_005_decision_snapshots",
        description="Create immutable decision_snapshots table for point-in-time decision audit.",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                decision_time TEXT NOT NULL,
                trade_id INTEGER,
                source TEXT NOT NULL,
                symbol TEXT,
                action TEXT,
                signal_price REAL,
                final_decision TEXT,
                approved INTEGER,
                rejection_reason TEXT,
                order_id TEXT,
                order_status TEXT,
                confidence TEXT,
                position_size_pct REAL,
                stop_loss_pct REAL,
                take_profit_pct REAL,
                macro_regime TEXT,
                risk_multiplier REAL,
                market_bias TEXT,
                market_bias_effective TEXT,
                market_bias_override_reason TEXT,
                fundamental_score TEXT,
                risk_level TEXT,
                entry_quality TEXT,
                trend_direction TEXT,
                trend_strength TEXT,
                momentum_direction TEXT,
                momentum_pct REAL,
                session_trend_label TEXT,
                session_trend_score REAL,
                session_return_pct REAL,
                session_momentum_5m_pct REAL,
                session_momentum_15m_pct REAL,
                session_momentum_30m_pct REAL,
                session_distance_from_vwap_pct REAL,
                session_momentum_reason TEXT,
                prediction_score REAL,
                prediction_decision TEXT,
                prediction_reason TEXT,
                correlation_cluster TEXT,
                cluster_exposure_pct REAL,
                setup_label TEXT,
                setup_policy_action TEXT,
                setup_policy_reason TEXT,
                setup_confidence_adjustment REAL,
                setup_size_multiplier REAL,
                buy_opportunity_score REAL,
                buy_opportunity_recommendation TEXT,
                buy_opportunity_reason TEXT,
                trader_brain_score REAL,
                trader_brain_setup_type TEXT,
                trader_brain_approved INTEGER,
                trader_brain_reason TEXT,
                market_context_date TEXT,
                market_context_hash TEXT,
                market_context_mtime TEXT,
                symbol_universe_version TEXT,
                env_profile_hash TEXT,
                git_sha TEXT,
                raw_signal_json TEXT,
                decision_json TEXT,
                order_json TEXT,
                account_state_json TEXT,
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_decision_snapshots_time
            ON decision_snapshots(decision_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_decision_snapshots_symbol_time
            ON decision_snapshots(symbol, decision_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_decision_snapshots_trade_id
            ON decision_snapshots(trade_id)
            """,
        ),
    ),
    Migration(
        migration_id="20260526_006_rejected_outcome_partial_reason",
        description="Add partial_reason to rejected_signal_outcomes for near-close/pending diagnostics.",
        statements=(
            "ALTER TABLE rejected_signal_outcomes ADD COLUMN partial_reason TEXT",
        ),
    ),
    Migration(
        migration_id="20260526_007_strong_day_participation",
        description="Create strong_day_participation table for prediction/intelligence validation.",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS strong_day_participation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_source TEXT,
                min_session_pct REAL NOT NULL,
                session_return_pct REAL,
                mfe_pct REAL,
                return_30m_pct REAL,
                return_60m_pct REAL,
                first_strong_time TEXT,
                session_high_time TEXT,
                primary_status TEXT,
                primary_blocker TEXT,
                buy_signal_count INTEGER,
                approved_buy_count INTEGER,
                rejected_buy_count INTEGER,
                sell_signal_count INTEGER,
                auto_buy_candidate_count INTEGER,
                auto_buy_strong_count INTEGER,
                auto_buy_watch_count INTEGER,
                auto_buy_submitted_count INTEGER,
                auto_buy_max_score REAL,
                auto_buy_first_candidate_time TEXT,
                auto_buy_first_strong_time TEXT,
                prediction_score REAL,
                prediction_decision TEXT,
                prediction_confidence TEXT,
                prediction_sample_size INTEGER,
                prediction_timing_score REAL,
                prediction_trend_score REAL,
                prediction_trend_label TEXT,
                raw_json TEXT,
                generated_at TEXT NOT NULL,
                UNIQUE(market_date, symbol, min_session_pct)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_strong_day_participation_date_symbol
            ON strong_day_participation(market_date, symbol)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_strong_day_participation_status
            ON strong_day_participation(market_date, primary_status)
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


def alter_table_add_column(statement: str) -> tuple[str, str] | None:
    normalized = " ".join(statement.strip().split())
    parts = normalized.split()
    if len(parts) < 6:
        return None
    if [p.upper() for p in parts[:5]] != ["ALTER", "TABLE", parts[2].upper(), "ADD", "COLUMN"]:
        return None
    return parts[2], parts[5]


def apply_migration(migration: Migration, db_path: Path | str = DB_PATH) -> bool:
    """Apply one migration if it is not already recorded."""
    ensure_migration_table(db_path)
    already_applied = applied_migrations(db_path)
    if migration.migration_id in already_applied:
        return False

    with get_connection(db_path) as con:
        for statement in migration.statements:
            alter = alter_table_add_column(statement)
            if alter:
                table, column = alter
                columns = table_columns(con, table)
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
