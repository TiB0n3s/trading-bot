"""
Focused tests for rejected-signal counterfactual outcome math.

Run:
  python3 tests/test_rejected_signal_outcomes.py
"""

import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from rejected_signal_outcome_builder import compute_outcome
from repositories.rejected_signal_outcome_repo import RejectedSignalOutcomeRepository
from services.rejected_signal_outcome_market_data_service import (
    RejectedSignalOutcomeMarketDataService,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_close(actual, expected, label, ndigits=6):
    if round(float(actual), ndigits) != round(float(expected), ndigits):
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def sample_bars():
    return [
        {"timestamp": "2026-05-26T09:35:00-04:00", "close": 100.0, "high": 100.2, "low": 99.8},
        {"timestamp": "2026-05-26T09:40:00-04:00", "close": 101.0, "high": 101.2, "low": 100.5},
        {"timestamp": "2026-05-26T09:50:00-04:00", "close": 102.0, "high": 102.4, "low": 100.8},
        {"timestamp": "2026-05-26T10:05:00-04:00", "close": 99.0, "high": 102.6, "low": 98.6},
        {"timestamp": "2026-05-26T10:35:00-04:00", "close": 103.0, "high": 103.5, "low": 98.5},
        {"timestamp": "2026-05-26T16:00:00-04:00", "close": 104.0, "high": 104.2, "low": 103.7},
    ]


def test_buy_outcome_uses_raw_forward_returns():
    outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T08:35:00-05:00",
            "action": "buy",
            "signal_price": 100.0,
        },
        sample_bars(),
    )

    assert_close(outcome["return_5m"], 1.0, "5m return")
    assert_close(outcome["return_15m"], 2.0, "15m return")
    assert_close(outcome["return_30m"], -1.0, "30m return")
    assert_close(outcome["return_60m"], 3.0, "60m return")
    assert_close(outcome["return_eod"], 4.0, "eod return")
    assert_close(outcome["max_favorable_60m"], 3.5, "mfe")
    assert_close(outcome["max_adverse_60m"], -1.5, "mae")
    assert_equal(outcome["label_status"], "labeled", "status")


def test_sell_outcome_is_action_adjusted():
    outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T08:35:00-05:00",
            "action": "sell",
            "signal_price": 100.0,
        },
        sample_bars(),
    )

    assert_close(outcome["return_5m"], -1.0, "5m return")
    assert_close(outcome["return_30m"], 1.0, "30m return")
    assert_close(outcome["max_favorable_60m"], 1.5, "sell mfe")
    assert_close(outcome["max_adverse_60m"], -3.5, "sell mae")


def test_near_close_partial_reason():
    outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T15:40:00-04:00",
            "action": "buy",
            "signal_price": 100.0,
        },
        [
            {"timestamp": "2026-05-26T15:45:00-04:00", "close": 100.2, "high": 100.3, "low": 99.9},
            {"timestamp": "2026-05-26T16:00:00-04:00", "close": 100.5, "high": 100.6, "low": 100.1},
        ],
    )

    assert_equal(outcome["label_status"], "partial", "status")
    assert_equal(outcome["partial_reason"], "near_close_no_60m_window", "partial reason")
    assert_equal(outcome["return_60m"], None, "near-close 60m")


def test_missing_forward_bars_partial_reason():
    outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T09:35:00-04:00",
            "action": "buy",
            "signal_price": 100.0,
        },
        [
            {"timestamp": "2026-05-26T09:40:00-04:00", "close": 101.0, "high": 101.2, "low": 99.9},
            {"timestamp": "2026-05-26T09:50:00-04:00", "close": 102.0, "high": 102.3, "low": 100.5},
        ],
    )

    assert_equal(outcome["label_status"], "partial", "status")
    assert_equal(outcome["partial_reason"], "missing_forward_bars", "partial reason")
    assert_close(outcome["return_5m"], 1.0, "5m return")
    assert_close(outcome["return_15m"], 2.0, "15m return")
    assert_equal(outcome["return_30m"], None, "30m return")


def test_excursions_are_action_adjusted_and_sign_bounded():
    buy_outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T08:35:00-05:00",
            "action": "buy",
            "signal_price": 100.0,
        },
        [
            {"timestamp": "2026-05-26T09:40:00-04:00", "close": 99.0, "high": 99.5, "low": 98.0},
            {"timestamp": "2026-05-26T10:35:00-04:00", "close": 98.5, "high": 99.4, "low": 97.0},
        ],
    )
    sell_outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T08:35:00-05:00",
            "action": "sell",
            "signal_price": 100.0,
        },
        [
            {"timestamp": "2026-05-26T09:40:00-04:00", "close": 101.0, "high": 102.0, "low": 100.5},
            {"timestamp": "2026-05-26T10:35:00-04:00", "close": 101.5, "high": 103.0, "low": 100.6},
        ],
    )

    assert_equal(buy_outcome["max_favorable_60m"], 0.0, "buy no-favorable mfe")
    assert_close(buy_outcome["max_adverse_60m"], -3.0, "buy adverse")
    assert_equal(sell_outcome["max_favorable_60m"], 0.0, "sell no-favorable mfe")
    assert_close(sell_outcome["max_adverse_60m"], -3.0, "sell adverse")


def test_repository_links_outcome_to_canonical_decision_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            con.execute(
                """
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    symbol TEXT,
                    action TEXT,
                    approved INTEGER,
                    signal_price REAL,
                    rejection_reason TEXT
                )
                """
            )
            trade_id = con.execute(
                """
                INSERT INTO trades (
                    timestamp, symbol, action, approved, signal_price, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "2026-05-26T09:35:00-04:00",
                    "AAPL",
                    "buy",
                    0,
                    100.0,
                    "prediction_gate:test",
                ),
            ).lastrowid
            con.execute(
                """
                CREATE TABLE decision_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER,
                    canonical_intelligence_version TEXT,
                    canonical_intelligence_hash TEXT,
                    canonical_intelligence_json TEXT
                )
                """
            )
            snapshot_id = con.execute(
                """
                INSERT INTO decision_snapshots (
                    trade_id,
                    canonical_intelligence_version,
                    canonical_intelligence_hash,
                    canonical_intelligence_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    trade_id,
                    "canonical_intelligence_v1",
                    "c" * 64,
                    '{"version":"canonical_intelligence_v1"}',
                ),
            ).lastrowid
            trade_row = con.execute(
                "SELECT id, timestamp, symbol, action, signal_price, rejection_reason FROM trades WHERE id = ?",
                (trade_id,),
            ).fetchone()

        repo = RejectedSignalOutcomeRepository(db_path)
        repo.upsert_outcome(
            trade_row,
            {
                "return_5m": 0.1,
                "return_15m": 0.2,
                "return_30m": 0.3,
                "return_60m": 0.4,
                "return_eod": 0.5,
                "max_favorable_60m": 0.8,
                "max_adverse_60m": -0.2,
                "label_status": "labeled",
            },
            "unit_test",
        )

        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            outcome = con.execute(
                "SELECT * FROM rejected_signal_outcomes WHERE trade_id = ?",
                (trade_id,),
            ).fetchone()

        assert_equal(outcome["decision_snapshot_id"], snapshot_id, "decision snapshot link")
        assert_equal(
            outcome["canonical_intelligence_version"],
            "canonical_intelligence_v1",
            "canonical version",
        )
        assert_equal(outcome["canonical_intelligence_hash"], "c" * 64, "canonical hash")
        assert_equal(
            outcome["canonical_intelligence_json"],
            '{"version":"canonical_intelligence_v1"}',
            "canonical json",
        )


def test_repository_labels_snapshot_only_rejections():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            con.execute(
                """
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE decision_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_time TEXT,
                    trade_id INTEGER,
                    symbol TEXT,
                    action TEXT,
                    signal_price REAL,
                    approved INTEGER,
                    rejection_reason TEXT,
                    canonical_intelligence_version TEXT,
                    canonical_intelligence_hash TEXT,
                    canonical_intelligence_json TEXT
                )
                """
            )
            snapshot_id = con.execute(
                """
                INSERT INTO decision_snapshots (
                    decision_time, trade_id, symbol, action, signal_price,
                    approved, rejection_reason, canonical_intelligence_version,
                    canonical_intelligence_hash, canonical_intelligence_json
                ) VALUES (?, NULL, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    "2026-05-26T09:35:00-04:00",
                    "AAPL",
                    "buy",
                    100.0,
                    "historical_bar_meta_label_veto",
                    "canonical_intelligence_v1",
                    "d" * 64,
                    '{"version":"canonical_intelligence_v1"}',
                ),
            ).lastrowid

        repo = RejectedSignalOutcomeRepository(db_path)
        rows = repo.rejected_decision_snapshot_rows(target_date="2026-05-26")
        assert_equal(len(rows), 1, "snapshot-only rejected row count")
        repo.upsert_decision_snapshot_outcome(
            rows[0],
            {
                "return_5m": 0.1,
                "return_15m": 0.2,
                "return_30m": 0.3,
                "return_60m": 0.4,
                "return_eod": 0.5,
                "max_favorable_60m": 0.8,
                "max_adverse_60m": -0.2,
                "label_status": "labeled",
            },
            "unit_test",
        )

        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            outcome = con.execute(
                "SELECT * FROM rejected_signal_outcomes WHERE decision_snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()

        assert_equal(outcome["trade_id"], None, "snapshot outcome has no trade id")
        assert_equal(outcome["decision_snapshot_id"], snapshot_id, "decision snapshot link")
        assert_equal(outcome["return_60m"], 0.4, "snapshot return")
        assert_equal(outcome["canonical_intelligence_hash"], "d" * 64, "canonical hash")


def test_rejected_signal_market_data_accepts_list_bar_responses():
    service = RejectedSignalOutcomeMarketDataService(market_data=SimpleNamespace())
    rows = service._barset_rows(
        [
            {
                "symbol": "AAPL",
                "timestamp": "2026-06-10T09:30:00-04:00",
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
            },
            {
                "symbol": "MSFT",
                "timestamp": "2026-06-10T09:30:00-04:00",
                "high": 201.0,
                "low": 199.5,
                "close": 200.5,
            },
        ],
        "AAPL",
    )

    assert_equal(len(rows), 1, "filtered rows")
    assert_equal(rows[0]["symbol"], "AAPL", "symbol")
    assert_equal(rows[0]["close"], 100.5, "close")


def main():
    tests = [
        test_buy_outcome_uses_raw_forward_returns,
        test_sell_outcome_is_action_adjusted,
        test_near_close_partial_reason,
        test_missing_forward_bars_partial_reason,
        test_excursions_are_action_adjusted_and_sign_bounded,
        test_repository_links_outcome_to_canonical_decision_snapshot,
        test_repository_labels_snapshot_only_rejections,
        test_rejected_signal_market_data_accepts_list_bar_responses,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} rejected-signal outcome tests passed.")


if __name__ == "__main__":
    main()
