#!/usr/bin/env python3
"""Tests for auto-buy repository query contracts."""

from __future__ import annotations

# ruff: noqa: E402
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from db import get_connection, init_prediction_tables

from repositories import auto_buy_repo


def test_latest_feature_uses_latest_inserted_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        init_prediction_tables(db_path)
        auto_buy_repo.init_tables(db_path)

        with get_connection(db_path) as con:
            con.execute(
                """
                INSERT INTO feature_snapshots (timestamp, symbol, last_price)
                VALUES (?, ?, ?)
                """,
                ("2026-06-12T14:00:00+00:00", "AAPL", 100.0),
            )
            con.execute(
                """
                INSERT INTO feature_snapshots (timestamp, symbol, last_price)
                VALUES (?, ?, ?)
                """,
                ("2026-06-12T14:01:00+00:00", "AAPL", 101.0),
            )

        row = auto_buy_repo.latest_feature("AAPL", db_path)

        assert row["symbol"] == "AAPL"
        assert row["last_price"] == 101.0


def test_insert_candidate_and_snapshot_retries_transient_database_lock():
    calls = {"n": 0}
    original_insert_once = auto_buy_repo._insert_candidate_and_snapshot_once
    original_sleep = auto_buy_repo.time.sleep

    def flaky_insert_once(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return None

    try:
        auto_buy_repo._insert_candidate_and_snapshot_once = flaky_insert_once
        auto_buy_repo.time.sleep = lambda _seconds: None
        auto_buy_repo.insert_candidate_and_snapshot(
            timestamp="2026-06-17T10:00:00-04:00",
            created_at="2026-06-17T10:00:00-04:00",
            candidate={"symbol": "AAPL", "decision": "skip"},
            live_buy_enabled=False,
            order={},
            candidate_json="{}",
            order_json="{}",
            db_path="unused.db",
        )
    finally:
        auto_buy_repo._insert_candidate_and_snapshot_once = original_insert_once
        auto_buy_repo.time.sleep = original_sleep

    assert calls["n"] == 2


def main():
    tests = [
        test_latest_feature_uses_latest_inserted_snapshot,
        test_insert_candidate_and_snapshot_retries_transient_database_lock,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} auto-buy repo tests passed.")


if __name__ == "__main__":
    main()
