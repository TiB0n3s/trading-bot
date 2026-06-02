#!/usr/bin/env python3
"""Tests for canonical lifecycle analysis rows."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.lifecycle_analysis_service import LifecycleAnalysisService


def _make_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                decision_time TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                final_decision TEXT,
                rejection_reason TEXT,
                canonical_intelligence_json TEXT,
                canonical_intelligence_version TEXT,
                canonical_intelligence_hash TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO decision_snapshots (
                id, trade_id, decision_time, symbol, action, approved,
                final_decision, rejection_reason, canonical_intelligence_json,
                canonical_intelligence_version, canonical_intelligence_hash
            ) VALUES
              (1, 10, '2026-05-31T14:30:00+00:00', 'AAPL', 'buy', 1,
               'approved', NULL, ?, 'canonical_intelligence_v1', ?),
              (2, 20, '2026-05-31T14:35:00+00:00', 'MSFT', 'buy', 0,
               'rejected', 'prediction_gate:test', ?, 'canonical_intelligence_v1', ?)
            """,
            (
                json.dumps(
                    {
                        "setup_state": {"label": "breakout"},
                        "regime_state": {
                            "market_regime": "trend_expansion",
                            "session_phase": "morning",
                            "execution_quality_decision": "allow",
                        },
                    }
                ),
                "a" * 64,
                json.dumps(
                    {
                        "setup_state": {"label": "late_chase"},
                        "regime_state": {
                            "market_regime": "compression_chop",
                            "session_phase": "midday",
                            "execution_quality_decision": "size_down",
                        },
                    }
                ),
                "b" * 64,
            ),
        )
        con.execute(
            """
            CREATE TABLE exit_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_trade_id INTEGER,
                exit_timestamp TEXT,
                exit_trigger TEXT,
                exit_source TEXT,
                realized_pnl REAL,
                realized_return_pct REAL,
                mfe_pct REAL,
                capture_ratio REAL,
                max_adverse_excursion_pct REAL,
                avoided_drawdown_pct REAL,
                missed_upside_pct REAL,
                reentry_window_summary TEXT,
                canonical_exit_version TEXT,
                canonical_exit_hash TEXT,
                entry_canonical_intelligence_hash TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO exit_snapshots (
                entry_trade_id, exit_timestamp, exit_trigger, exit_source,
                realized_pnl, realized_return_pct, mfe_pct, capture_ratio,
                max_adverse_excursion_pct, avoided_drawdown_pct, missed_upside_pct,
                reentry_window_summary, canonical_exit_version, canonical_exit_hash,
                entry_canonical_intelligence_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                10,
                "2026-05-31T15:20:00+00:00",
                "peak_lock_floor",
                "position_manager",
                12.5,
                0.42,
                0.8,
                0.525,
                -0.35,
                0.3,
                0.1,
                "no_clean_reentry_60m",
                "canonical_exit_v1",
                "c" * 64,
                "a" * 64,
            ),
        )
        con.execute(
            """
            CREATE TABLE rejected_signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                decision_snapshot_id INTEGER,
                label_status TEXT,
                return_30m REAL,
                return_60m REAL,
                return_eod REAL,
                max_favorable_60m REAL,
                max_adverse_60m REAL,
                canonical_intelligence_hash TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO rejected_signal_outcomes (
                trade_id, decision_snapshot_id, label_status, return_30m,
                return_60m, return_eod, max_favorable_60m, max_adverse_60m,
                canonical_intelligence_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (20, 2, "labeled", 0.3, 0.6, 0.7, 0.9, -0.2, "b" * 64),
        )


def test_lifecycle_analysis_joins_entry_exit_and_rejected_counterfactuals():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        _make_db(db_path)

        service = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
        payload = service.payload(start_date="2026-05-31")

        assert payload.summary == {
            "rows": 2,
            "approved_with_exit": 1,
            "approved_open_or_unlinked_exit": 0,
            "rejected_with_counterfactual": 1,
            "rejected_snapshot_only_no_trade": 0,
            "rejected_without_counterfactual": 0,
            "rejected_counterfactual_coverage_rate": 1.0,
            "approved_exit_link_rate": 1.0,
            "analysis_ready": True,
        }

        approved = payload.rows[0]
        rejected = payload.rows[1]
        assert approved["lifecycle_status"] == "approved_with_exit"
        assert approved["setup_label"] == "breakout"
        assert rejected["market_regime"] == "compression_chop"
        assert approved["entry_canonical_intelligence_hash"] == "a" * 64
        assert approved["canonical_exit_hash"] == "c" * 64
        assert approved["exit_trigger"] == "peak_lock_floor"
        assert approved["capture_ratio"] == 0.525
        assert rejected["lifecycle_status"] == "rejected_with_counterfactual"
        assert rejected["rejected_label_status"] == "labeled"
        assert rejected["rejected_canonical_intelligence_hash"] == "b" * 64
        assert rejected["rejected_return_eod"] == 0.7


def test_lifecycle_analysis_flags_missing_rejected_counterfactuals():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE decision_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER,
                    decision_time TEXT,
                    symbol TEXT,
                    action TEXT,
                    approved INTEGER,
                    final_decision TEXT,
                    rejection_reason TEXT,
                    canonical_intelligence_version TEXT,
                    canonical_intelligence_hash TEXT
                )
                """
            )
            con.execute(
                """
                INSERT INTO decision_snapshots (
                    trade_id, decision_time, symbol, action, approved,
                    final_decision, rejection_reason, canonical_intelligence_version,
                    canonical_intelligence_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    20,
                    "2026-05-31T14:35:00+00:00",
                    "MSFT",
                    "buy",
                    0,
                    "rejected",
                    "prediction_gate:test",
                    "canonical_intelligence_v1",
                    "b" * 64,
                ),
            )

        service = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
        payload = service.payload(start_date="2026-05-31")

        assert payload.summary["rows"] == 1
        assert payload.summary["rejected_without_counterfactual"] == 1
        assert payload.rows[0]["lifecycle_status"] == "rejected_without_counterfactual"


def test_lifecycle_analysis_classifies_snapshot_only_rejections():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE decision_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER,
                    decision_time TEXT,
                    symbol TEXT,
                    action TEXT,
                    approved INTEGER,
                    final_decision TEXT,
                    rejection_reason TEXT,
                    canonical_intelligence_version TEXT,
                    canonical_intelligence_hash TEXT
                )
                """
            )
            con.execute(
                """
                INSERT INTO decision_snapshots (
                    trade_id, decision_time, symbol, action, approved,
                    final_decision, rejection_reason, canonical_intelligence_version,
                    canonical_intelligence_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    None,
                    "2026-05-31T14:35:00+00:00",
                    "META",
                    "sell",
                    0,
                    "no_replace_now",
                    "recommendation=observe_only",
                    "canonical_intelligence_v1",
                    "b" * 64,
                ),
            )

        service = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
        payload = service.payload(start_date="2026-05-31")

        assert payload.summary["rows"] == 1
        assert payload.summary["rejected_snapshot_only_no_trade"] == 1
        assert payload.summary["rejected_without_counterfactual"] == 0
        assert payload.rows[0]["lifecycle_status"] == "rejected_snapshot_only_no_trade"


def test_lifecycle_analysis_tolerates_pre_canonical_schema():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE decision_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER,
                    decision_time TEXT,
                    symbol TEXT,
                    action TEXT,
                    approved INTEGER,
                    final_decision TEXT,
                    rejection_reason TEXT
                )
                """
            )
            con.execute(
                """
                INSERT INTO decision_snapshots (
                    id, trade_id, decision_time, symbol, action, approved,
                    final_decision, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    2,
                    20,
                    "2026-05-29 14:35:00",
                    "MSFT",
                    "buy",
                    0,
                    "rejected",
                    "prediction_gate:test",
                ),
            )
            con.execute(
                """
                CREATE TABLE rejected_signal_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER,
                    label_status TEXT,
                    return_30m REAL,
                    return_60m REAL,
                    return_eod REAL,
                    max_favorable_60m REAL,
                    max_adverse_60m REAL
                )
                """
            )
            con.execute(
                """
                INSERT INTO rejected_signal_outcomes (
                    trade_id, label_status, return_30m, return_60m,
                    return_eod, max_favorable_60m, max_adverse_60m
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (20, "labeled", 0.2, 0.4, 0.5, 0.7, -0.1),
            )

        service = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
        payload = service.payload(start_date="2026-05-29")

        assert payload.summary["rows"] == 1
        assert payload.summary["rejected_with_counterfactual"] == 1
        row = payload.rows[0]
        assert row["lifecycle_status"] == "rejected_with_counterfactual"
        assert row["entry_canonical_intelligence_hash"] is None
        assert row["entry_canonical_intelligence_version"] is None
        assert row["rejected_canonical_intelligence_hash"] is None
        assert row["rejected_return_60m"] == 0.4
        assert row["rejected_return_eod"] == 0.5


def main():
    tests = [
        test_lifecycle_analysis_joins_entry_exit_and_rejected_counterfactuals,
        test_lifecycle_analysis_flags_missing_rejected_counterfactuals,
        test_lifecycle_analysis_classifies_snapshot_only_rejections,
        test_lifecycle_analysis_tolerates_pre_canonical_schema,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} lifecycle analysis service tests passed.")


if __name__ == "__main__":
    main()
