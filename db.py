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
    """Return a configured SQLite connection."""
    con = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    con.row_factory = sqlite3.Row

    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA foreign_keys=ON")

    return con


def init_prediction_tables(db_path: Path | str = DB_PATH) -> None:
    """Create observe-only prediction tables and indexes."""
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS feature_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                last_price REAL,
                ret_1m REAL,
                ret_5m REAL,
                ret_15m REAL,
                range_pos_15m REAL,
                distance_from_5m_high REAL,
                distance_from_5m_low REAL,
                distance_from_vwap REAL,
                volume_ratio_5m REAL,
                benchmark_symbol TEXT,
                benchmark_ret_5m REAL,
                relative_strength_5m REAL,
                spread_pct REAL,
                market_session TEXT,
                macro_regime TEXT,
                market_bias TEXT,
                trend_direction TEXT,
                trend_strength TEXT,
                bar_timeframe TEXT,
                bar_count INTEGER,
                setup_label TEXT,
                setup_recommendation TEXT,
                setup_score INTEGER,
                setup_confidence TEXT,
                setup_key TEXT
            )
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_feature_snapshots_symbol_timestamp
            ON feature_snapshots(symbol, timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_feature_snapshots_timestamp
            ON feature_snapshots(timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_feature_snapshots_symbol_id
            ON feature_snapshots(symbol, id)
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS labeled_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER UNIQUE,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                price_at_snapshot REAL,
                future_price_5m REAL,
                future_price_15m REAL,
                future_price_30m REAL,
                ret_fwd_5m REAL,
                ret_fwd_15m REAL,
                ret_fwd_30m REAL,
                max_up_15m REAL,
                max_down_15m REAL,
                outcome_label TEXT,
                FOREIGN KEY (snapshot_id) REFERENCES feature_snapshots(id)
            )
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_labeled_setups_symbol_timestamp
            ON labeled_setups(symbol, timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_labeled_setups_outcome_label
            ON labeled_setups(outcome_label)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_labeled_setups_snapshot_id
            ON labeled_setups(snapshot_id)
            """
        )

        existing_cols = {
            row["name"]
            for row in con.execute("PRAGMA table_info(feature_snapshots)").fetchall()
        }

        feature_snapshot_cols = [
            ("bar_timeframe", "TEXT"),
            ("bar_count", "INTEGER"),
            ("setup_label", "TEXT"),
            ("setup_recommendation", "TEXT"),
            ("setup_score", "INTEGER"),
            ("setup_confidence", "TEXT"),
            ("setup_key", "TEXT"),
        ]
        for col_name, col_type in feature_snapshot_cols:
            if col_name not in existing_cols:
                con.execute(
                    f"ALTER TABLE feature_snapshots ADD COLUMN {col_name} {col_type}"
                )


def init_db_performance_indexes(db_path: Path | str = DB_PATH) -> None:
    """Create useful indexes for webhook checks, reports, and reconciliation."""
    with get_connection(db_path) as con:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id)"
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trades_approved_status_timestamp
            ON trades(approved, order_status, timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trades_symbol_action_timestamp
            ON trades(symbol, action, timestamp)
            """
        )

        existing = {
            row["name"]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "recent_webhooks" in existing:
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_recent_webhooks_first_seen
                ON recent_webhooks(first_seen)
                """
            )

        if "fill_events" in existing:
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fill_events_timestamp
                ON fill_events(timestamp)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fill_events_order_id
                ON fill_events(order_id)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fill_events_symbol_timestamp
                ON fill_events(symbol, timestamp)
                """
            )

    init_prediction_tables(db_path)


def db_health_summary(db_path: Path | str = DB_PATH) -> dict:
    """Return a small DB health summary for diagnostics."""
    with get_connection(db_path) as con:
        tables = [
            row["name"]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]

        summary = {"db_path": str(db_path), "tables": tables}

        if "trades" in tables:
            summary["trades_count"] = con.execute(
                "SELECT COUNT(*) AS n FROM trades"
            ).fetchone()["n"]

        if "fill_events" in tables:
            summary["fill_events_count"] = con.execute(
                "SELECT COUNT(*) AS n FROM fill_events"
            ).fetchone()["n"]

        if "matched_trades" in tables:
            summary["matched_trades_count"] = con.execute(
                "SELECT COUNT(*) AS n FROM matched_trades"
            ).fetchone()["n"]

        if "feature_snapshots" in tables:
            summary["feature_snapshots_count"] = con.execute(
                "SELECT COUNT(*) AS n FROM feature_snapshots"
            ).fetchone()["n"]

        if "labeled_setups" in tables:
            summary["labeled_setups_count"] = con.execute(
                "SELECT COUNT(*) AS n FROM labeled_setups"
            ).fetchone()["n"]

        return summary