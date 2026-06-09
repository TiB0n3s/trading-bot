#!/usr/bin/env python3
"""Tests for trace-native decision reports."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.decision.trace_reports import (  # noqa: E402
    counterfactual_replay_summary,
    decision_trace_summary,
    gate_impact_summary,
    load_trace_rows,
    model_authority_summary,
)


def test_trace_reports_load_and_summarize_decision_snapshots():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        trace = {
            "trace_version": "decision_trace_v1",
            "final_decision": "approved",
            "blocking_gate": None,
            "dominant_limiter": "final_sizing",
            "gate_results": [
                {
                    "gate_id": "prediction",
                    "layer": "prediction",
                    "decision": "pass",
                    "enforced": False,
                },
                {
                    "gate_id": "paper_exploration_authority",
                    "layer": "authority",
                    "decision": "pass",
                    "enforced": True,
                },
            ],
            "shadow": {"approval_source": "paper_exploration_authority"},
        }
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE decision_snapshots (
                    id INTEGER PRIMARY KEY,
                    decision_time TEXT,
                    symbol TEXT,
                    action TEXT,
                    final_decision TEXT,
                    rejection_reason TEXT,
                    account_state_json TEXT
                )
                """
            )
            con.execute(
                """
                INSERT INTO decision_snapshots (
                    decision_time, symbol, action, final_decision,
                    rejection_reason, account_state_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "2026-06-09T10:00:00",
                    "AAPL",
                    "buy",
                    "approved",
                    None,
                    json.dumps({"canonical_decision_trace": trace}),
                ),
            )
        rows = load_trace_rows(db_path=db_path, target_date="2026-06-09")
        assert len(rows) == 1
        assert decision_trace_summary(rows)["dominant_limiters"]["final_sizing"] == 1
        assert gate_impact_summary(rows)["paper_exploration_authority"]["pass:enforced"] == 1
        assert model_authority_summary(rows)["approval_sources"]["paper_exploration_authority"] == 1
        assert counterfactual_replay_summary(rows)["changed_decisions"] == 1


def main():
    tests = [test_trace_reports_load_and_summarize_decision_snapshots]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} decision trace report tests passed.")


if __name__ == "__main__":
    main()
