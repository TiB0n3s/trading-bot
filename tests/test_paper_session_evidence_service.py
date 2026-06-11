#!/usr/bin/env python3
"""Tests for paper-session evidence aggregation."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.paper_session_evidence_service import (  # noqa: E402
    build_paper_session_evidence_payload,
)


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY,
                decision_time TEXT,
                canonical_intelligence_json TEXT,
                account_state_json TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE candidate_universe (
                id INTEGER PRIMARY KEY,
                candidate_ts TEXT,
                symbol TEXT,
                candidate_status TEXT,
                decision TEXT,
                candidate_json TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE auto_buy_decision_snapshots (
                id INTEGER PRIMARY KEY,
                candidate_timestamp TEXT,
                order_submitted INTEGER,
                execution_status TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE auto_buy_candidates (
                id INTEGER PRIMARY KEY,
                timestamp TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE auto_buy_intraday_feedback (
                id INTEGER PRIMARY KEY,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE rejected_signal_outcomes (
                id INTEGER PRIMARY KEY,
                created_at TEXT,
                label_status TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE matched_trades (
                id INTEGER PRIMARY KEY,
                entry_timestamp TEXT
            )
            """
        )


def test_paper_session_evidence_reports_clean_when_learning_effect_and_outcomes_exist():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        _build_db(db_path)
        with sqlite3.connect(db_path) as con:
            canonical = {
                "advisory_authority_state": {
                    "decision_policy_outcome": {
                        "advisory_decision": "allow",
                        "effect_on_execution": "allow",
                    }
                }
            }
            con.execute(
                """
                INSERT INTO decision_snapshots (
                    decision_time, canonical_intelligence_json, account_state_json
                ) VALUES (?, ?, ?)
                """,
                ("2026-06-11T10:00:00Z", json.dumps(canonical), "{}"),
            )
            candidate = {"forward_return_pct": 1.2}
            con.execute(
                """
                INSERT INTO candidate_universe (
                    candidate_ts, symbol, candidate_status, decision, candidate_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("2026-06-11T10:00:00Z", "AAPL", "taken", "submitted", json.dumps(candidate)),
            )
            con.execute(
                """
                INSERT INTO auto_buy_decision_snapshots (
                    candidate_timestamp, order_submitted, execution_status
                ) VALUES (?, ?, ?)
                """,
                ("2026-06-11T10:00:00Z", 1, "ROUTED"),
            )
            con.execute("INSERT INTO auto_buy_candidates (timestamp) VALUES (?)", ("2026-06-11",))
            con.execute(
                "INSERT INTO auto_buy_intraday_feedback (created_at) VALUES (?)",
                ("2026-06-11T10:05:00Z",),
            )
            con.execute(
                """
                INSERT INTO rejected_signal_outcomes (created_at, label_status)
                VALUES (?, ?)
                """,
                ("2026-06-11T11:00:00Z", "COMPLETED"),
            )
            con.execute(
                "INSERT INTO matched_trades (entry_timestamp) VALUES (?)",
                ("2026-06-11T12:00:00Z",),
            )

        payload = build_paper_session_evidence_payload(
            db_path=db_path,
            target_date="2026-06-11",
        )

        assert payload.clean_for_authority_review is True
        assert payload.decision_snapshots["decision_policy_learning_effect_rows"] == 1
        assert payload.candidate_universe["forward_outcome_coverage_rate"] == 1.0
        assert payload.auto_buy["bridge_routed_rows"] == 1
        assert payload.outcomes["rejected_completed"] == 1


def test_paper_session_evidence_flags_missing_learning_effect():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        _build_db(db_path)
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                INSERT INTO decision_snapshots (
                    decision_time, canonical_intelligence_json, account_state_json
                ) VALUES (?, ?, ?)
                """,
                ("2026-06-11T10:00:00Z", "{}", "{}"),
            )

        payload = build_paper_session_evidence_payload(
            db_path=db_path,
            target_date="2026-06-11",
        )

        assert payload.clean_for_authority_review is False
        assert "decision_policy_learning_effect_not_recorded" in payload.blockers


def main():
    tests = [
        test_paper_session_evidence_reports_clean_when_learning_effect_and_outcomes_exist,
        test_paper_session_evidence_flags_missing_learning_effect,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} paper-session evidence service tests passed.")


if __name__ == "__main__":
    main()
