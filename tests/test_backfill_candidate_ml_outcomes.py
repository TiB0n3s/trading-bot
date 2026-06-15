"""Tests for ML-bearing candidate forward outcome backfill."""

import json
import sqlite3

from scripts.backfill_candidate_ml_outcomes import backfill


def test_backfill_candidate_ml_outcomes_updates_only_ml_rows(tmp_path):
    db_path = tmp_path / "trades.db"
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE candidate_universe (
                id INTEGER PRIMARY KEY,
                candidate_ts TEXT,
                symbol TEXT,
                action TEXT,
                candidate_json TEXT
            );
            CREATE TABLE feature_snapshots (
                timestamp TEXT,
                symbol TEXT,
                last_price REAL
            );
            """
        )
        con.execute(
            """
            INSERT INTO candidate_universe VALUES (
                1,
                '2026-06-15T10:00:00-04:00',
                'AAPL',
                'buy',
                '{"candidate":{"current_price":100.0,
                  "layered_ml_final_instruction":"paper_approval",
                  "probability_pct":70.0,
                  "confluence_score":24.0,
                  "conviction_score":24.0}}'
            )
            """
        )
        con.execute(
            """
            INSERT INTO candidate_universe VALUES (
                2,
                '2026-06-15T10:00:00-04:00',
                'MSFT',
                'buy',
                '{"candidate":{"current_price":100.0}}'
            )
            """
        )
        con.executemany(
            "INSERT INTO feature_snapshots VALUES (?, ?, ?)",
            [
                ("2026-06-15T10:00:00-04:00", "AAPL", 100.0),
                ("2026-06-15T10:05:00-04:00", "AAPL", 101.0),
                ("2026-06-15T10:30:00-04:00", "AAPL", 102.0),
                ("2026-06-15T11:00:00-04:00", "AAPL", 103.0),
                ("2026-06-15T15:59:00-04:00", "AAPL", 104.0),
                ("2026-06-15T11:00:00-04:00", "MSFT", 103.0),
            ],
        )
        con.commit()
    finally:
        con.close()

    result = backfill(db_path, "2026-06-15")

    assert result["eligible"] == 1
    assert result["updated"] == 1
    assert result["after"]["ml_rows_with_forward"] == 1

    con = sqlite3.connect(db_path)
    try:
        payload = json.loads(
            con.execute(
                "SELECT candidate_json FROM candidate_universe WHERE id = 1"
            ).fetchone()[0]
        )
        untouched = json.loads(
            con.execute(
                "SELECT candidate_json FROM candidate_universe WHERE id = 2"
            ).fetchone()[0]
        )
    finally:
        con.close()

    assert payload["return_5m"] == 1.0
    assert payload["return_60m"] == 3.0
    assert payload["forward_return_pct"] == 3.0
    assert payload["forward_mfe_pct"] == 3.0
    assert payload["candidate"]["layered_ml_final_instruction"] == "paper_approval"
    assert "forward_return_pct" not in untouched


def test_backfill_candidate_ml_outcomes_uses_candidate_quote_path_when_no_features(tmp_path):
    db_path = tmp_path / "trades.db"
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE candidate_universe (
                id INTEGER PRIMARY KEY,
                candidate_ts TEXT,
                symbol TEXT,
                action TEXT,
                candidate_json TEXT
            );
            CREATE TABLE feature_snapshots (
                timestamp TEXT,
                symbol TEXT,
                last_price REAL
            );
            """
        )
        con.executemany(
            "INSERT INTO candidate_universe VALUES (?, ?, ?, ?, ?)",
            [
                (
                    1,
                    "2026-06-15T10:00:00-04:00",
                    "JNPR",
                    "buy",
                    '{"candidate":{"bid":39.90,"ask":40.10,'
                    '"layered_ml_final_instruction":"paper_approval"}}',
                ),
                (
                    2,
                    "2026-06-15T11:00:00-04:00",
                    "JNPR",
                    "buy",
                    '{"candidate":{"bid":40.90,"ask":41.10,'
                    '"layered_ml_final_instruction":"paper_approval"}}',
                ),
            ],
        )
        con.commit()
    finally:
        con.close()

    result = backfill(db_path, "2026-06-15", limit=1)

    assert result["eligible"] == 1
    assert result["updated"] == 1
    con = sqlite3.connect(db_path)
    try:
        payload = json.loads(
            con.execute(
                "SELECT candidate_json FROM candidate_universe WHERE id = 1"
            ).fetchone()[0]
        )
    finally:
        con.close()

    assert payload["forward_reference_price_source"] == "first_bar_close_at_or_after_candidate_ts"
    assert payload["candidate_outcome_price_path_source"] == "candidate_universe_quote_path"
    assert payload["return_60m"] == 2.5
