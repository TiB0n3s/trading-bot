"""Tests for the ML edge analysis utility."""

import sqlite3

from scripts.analyze_ml_edge import (
    calibration,
    edge_by_group,
    load_candidate_universe,
    load_rejected_outcomes,
    score_window,
)


def test_analyze_ml_edge_loads_candidate_and_rejected_sources(tmp_path):
    db_path = tmp_path / "edge.db"
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE candidate_universe (
                candidate_ts TEXT,
                symbol TEXT,
                candidate_status TEXT,
                score REAL,
                reason TEXT,
                candidate_json TEXT
            );
            CREATE TABLE auto_buy_decision_snapshots (
                id INTEGER PRIMARY KEY,
                candidate_timestamp TEXT,
                symbol TEXT,
                decision TEXT,
                score REAL,
                reason TEXT,
                candidate_json TEXT
            );
            CREATE TABLE rejected_signal_outcomes (
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                return_60m REAL,
                return_30m REAL,
                return_eod REAL,
                max_favorable_60m REAL,
                rejection_reason TEXT,
                decision_snapshot_id INTEGER
            );
            """
        )
        con.execute(
            """
            INSERT INTO candidate_universe VALUES (
                '2026-06-15T10:00:00-05:00',
                'AAPL',
                'near_threshold',
                22.0,
                'layered_ml_approval',
                '{"candidate":{"conviction_score":22.0,"probability_pct":70.0,
                  "probability_source":"daily_symbol_predictions:probability_of_profit",
                  "layered_ml_final_instruction":"paper_approval",
                  "forward_return_pct":0.6,"forward_mfe_pct":1.2}}'
            )
            """
        )
        con.execute(
            """
            INSERT INTO auto_buy_decision_snapshots VALUES (
                1,
                '2026-06-15T10:02:00-05:00',
                'MSFT',
                'skip',
                18.0,
                'layered_ml_veto',
                '{"layered_ml_final_instruction":"veto",
                  "layered_ml_ensemble_probability_pct":40.0,
                  "conviction_score":18.0}'
            )
            """
        )
        con.execute(
            """
            INSERT INTO rejected_signal_outcomes VALUES (
                '2026-06-15T10:02:00-05:00',
                'MSFT',
                'buy',
                -0.4,
                NULL,
                NULL,
                0.2,
                'blocked',
                1
            )
            """
        )
        con.commit()

        con.row_factory = sqlite3.Row
        candidate_rows = load_candidate_universe(con, "2026-06-15", "2026-06-16", None)
        rejected_rows = load_rejected_outcomes(con, "2026-06-15", "2026-06-16", None)
    finally:
        con.close()

    assert len(candidate_rows) == 1
    assert candidate_rows[0].instruction_class == "approve"
    assert candidate_rows[0].probability_pct == 70.0
    assert candidate_rows[0].forward_return_pct == 0.6
    assert len(rejected_rows) == 1
    assert rejected_rows[0].instruction_class == "caution"
    assert rejected_rows[0].forward_return_pct == -0.4

    rows = candidate_rows + rejected_rows
    assert calibration(rows, 10)[0]["n"] == 1
    edge = {item["group"]: item for item in edge_by_group(rows, "instruction_class")}
    assert edge["approve"]["win_pct"] == 100.0
    assert edge["caution"]["win_pct"] == 0.0
    windows = {item["group"]: item for item in score_window(rows, 23.0)}
    assert windows["near_window"]["n"] == 1
    assert windows["below_window"]["n"] == 1
