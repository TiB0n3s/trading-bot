#!/usr/bin/env python3
"""Tests for auto-buy repository query contracts."""

from __future__ import annotations

# ruff: noqa: E402
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


def main():
    tests = [test_latest_feature_uses_latest_inserted_snapshot]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} auto-buy repo tests passed.")


if __name__ == "__main__":
    main()
