#!/usr/bin/env python3
"""Tests for experience-model probability coverage fallbacks."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from repositories.experience_model_repo import ExperienceModelRepository

from market_intelligence.experience_model import prediction_from_matches


def test_prediction_uses_candidate_forward_outcomes_when_closed_trades_absent():
    prediction = prediction_from_matches(
        target_ctx={
            "catalyst_score": 50,
            "supply_chain_risk_score": 50,
            "competitive_risk_score": 50,
        },
        matches=[
            {
                "similarity_score": 90,
                "context": {"market_date": "2026-06-01", "symbol": "AAPL"},
                "reasons": ["same_symbol"],
                "outcome": {
                    "signals": 1,
                    "approved": 0,
                    "orders": 0,
                    "closed_trades": 0,
                    "realized_pnl": 0,
                    "expectancy": None,
                    "win_rate": None,
                    "profit_evidence_count": 3,
                    "profit_evidence_wins": 2,
                    "profit_evidence_source": "candidate_forward_outcomes",
                },
            },
            {
                "similarity_score": 80,
                "context": {"market_date": "2026-06-02", "symbol": "MSFT"},
                "reasons": ["macro_regime"],
                "outcome": {
                    "signals": 1,
                    "approved": 0,
                    "orders": 0,
                    "closed_trades": 0,
                    "realized_pnl": 0,
                    "expectancy": None,
                    "win_rate": None,
                    "profit_evidence_count": 1,
                    "profit_evidence_wins": 0,
                    "profit_evidence_source": "candidate_forward_outcomes",
                },
            },
        ],
    )

    assert prediction["probability_of_profit"] == 0.5
    assert prediction["probability_of_profit_source"] == "candidate_forward_outcomes"
    assert prediction["probability_of_profit_sample_size"] == 4
    assert prediction["expected_pnl"] is None
    assert prediction["expected_win_rate"] is None
    assert prediction["raw"]["profit_evidence_sample_size"] == 4
    assert prediction["raw"]["profit_evidence_sources"] == ["candidate_forward_outcomes"]
    assert "candidate_forward_outcomes" in prediction["reason"]


def test_candidate_forward_outcome_lookup_reads_materialized_candidate_labels():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        with sqlite3.connect(db_path) as con:
            con.execute(
                """
                CREATE TABLE candidate_universe (
                    id INTEGER PRIMARY KEY,
                    candidate_ts TEXT,
                    symbol TEXT,
                    candidate_status TEXT,
                    score REAL,
                    candidate_json TEXT
                )
                """
            )
            con.execute(
                """
                INSERT INTO candidate_universe VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "2026-06-10T10:00:00-05:00",
                    "MSFT",
                    "scored_not_taken",
                    22.0,
                    json.dumps({"candidate": {"forward_return_pct": 0.42}}),
                ),
            )
            con.execute(
                """
                INSERT INTO candidate_universe VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    2,
                    "2026-06-11T10:00:00-05:00",
                    "MSFT",
                    "scored_not_taken",
                    21.0,
                    json.dumps({"candidate": {"forward_return_pct": -0.25}}),
                ),
            )

        rows = ExperienceModelRepository(db_path).candidate_forward_outcome_rows_for_context(
            "2026-06-10",
            "msft",
        )

        assert len(rows) == 1
        assert rows[0]["symbol"] == "MSFT"
        assert rows[0]["forward_return_pct"] == 0.42


if __name__ == "__main__":
    test_prediction_uses_candidate_forward_outcomes_when_closed_trades_absent()
    test_candidate_forward_outcome_lookup_reads_materialized_candidate_labels()
    print("experience model probability tests passed")
