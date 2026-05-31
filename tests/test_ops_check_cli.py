#!/usr/bin/env python3
"""Lightweight tests for ops_check.py command routing."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ops_check


def _run_cli(tmp_path: Path, *args: str) -> tuple[int, str]:
    old_argv = sys.argv[:]
    old_base = ops_check.BASE_DIR
    old_env_file = ops_check.ENV_FILE
    try:
        sys.argv = ["ops_check.py", *args]
        ops_check.BASE_DIR = tmp_path
        ops_check.ENV_FILE = tmp_path / "missing.env"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ops_check.main()
        return code, buf.getvalue()
    finally:
        sys.argv = old_argv
        ops_check.BASE_DIR = old_base
        ops_check.ENV_FILE = old_env_file


def _canonical_lifecycle_json(
    *,
    regime="trend_expansion",
    execution="allow",
    portfolio="allow",
    breakout="confirmed_expansion_breakout",
    participation="confirmed",
    volatility="low",
    structure="high_quality_structure",
    downside="contained_downside",
    utility="trade_candidate",
    setup="breakout",
    phase="first_30m",
) -> str:
    return json.dumps(
        {
            "regime_state": {
                "market_regime": regime,
                "execution_quality_decision": execution,
                "portfolio_decision": portfolio,
                "breakout_quality": breakout,
                "participation_state": participation,
                "volatility_chase_risk": volatility,
                "downside_state": downside,
                "session_phase": phase,
            },
            "setup_state": {
                "label": setup,
                "structure_state": structure,
            },
            "advisory_authority_state": {
                "utility_estimate": {"utility_decision": utility}
            },
        }
    )


def _create_lifecycle_fixture_db(tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "trades.db") as con:
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
                canonical_intelligence_hash TEXT,
                canonical_intelligence_json TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE exit_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_trade_id INTEGER,
                exit_timestamp TEXT,
                exit_trigger TEXT,
                realized_return_pct REAL,
                mfe_pct REAL,
                max_adverse_excursion_pct REAL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE rejected_signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_snapshot_id INTEGER,
                return_60m REAL,
                max_favorable_60m REAL,
                max_adverse_60m REAL,
                label_status TEXT
            )
            """
        )
        rows = [
            (
                1,
                "2026-05-30T10:00:00+00:00",
                "AAPL",
                1,
                "approved",
                None,
                _canonical_lifecycle_json(),
            ),
            (
                2,
                "2026-05-30T10:30:00+00:00",
                "MSFT",
                1,
                "approved",
                None,
                _canonical_lifecycle_json(
                    regime="orderly_pullback",
                    execution="allow",
                    portfolio="diversifying",
                    breakout="range_retest",
                    participation="mixed",
                    volatility="normal",
                    structure="clean_retest",
                    downside="contained_downside",
                    utility="trade_candidate",
                    setup="pullback",
                    phase="late_morning",
                ),
            ),
            (
                3,
                "2026-05-30T12:00:00+00:00",
                "NVDA",
                0,
                "rejected",
                "trend_confirmation",
                _canonical_lifecycle_json(
                    regime="compression_chop",
                    execution="size_down",
                    portfolio="duplicate_risk",
                    breakout="liquidity_vacuum_breakout",
                    participation="isolated_or_weak",
                    volatility="high",
                    structure="messy_range",
                    downside="asymmetric_downside_high",
                    utility="do_not_trade",
                    setup="late_chase",
                    phase="midday",
                ),
            ),
            (
                4,
                "2026-05-30T14:00:00+00:00",
                "TSLA",
                0,
                "rejected",
                "prediction_gate",
                _canonical_lifecycle_json(
                    regime="risk_off_unwind",
                    execution="avoid",
                    portfolio="duplicate_risk",
                    breakout="failed_auction",
                    participation="weak",
                    volatility="extreme_stretch",
                    structure="failed_breakout",
                    downside="event_risk_high",
                    utility="do_not_trade",
                    setup="failed_breakout",
                    phase="afternoon",
                ),
            ),
        ]
        con.executemany(
            """
            INSERT INTO decision_snapshots (
                trade_id, decision_time, symbol, action, approved, final_decision,
                rejection_reason, canonical_intelligence_json
            ) VALUES (?, ?, ?, 'buy', ?, ?, ?, ?)
            """,
            rows,
        )
        con.executemany(
            """
            INSERT INTO exit_snapshots (
                entry_trade_id, exit_timestamp, exit_trigger,
                realized_return_pct, mfe_pct, max_adverse_excursion_pct
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "2026-05-30T11:00:00+00:00", "target", 0.8, 1.2, -0.2),
                (2, "2026-05-30T11:30:00+00:00", "trail", 0.3, 0.6, -0.1),
            ],
        )
        con.executemany(
            """
            INSERT INTO rejected_signal_outcomes (
                decision_snapshot_id, return_60m, max_favorable_60m,
                max_adverse_60m, label_status
            ) VALUES (?, ?, ?, ?, 'complete')
            """,
            [
                (3, -0.4, 0.1, -0.8),
                (4, -0.7, 0.0, -1.1),
            ],
        )


def test_feature_attribution_cli_missing_db_exits_cleanly(tmp_path):
    code, out = _run_cli(tmp_path, "feature-attribution", "2026-05-30")

    assert code == 1
    assert "Feature Attribution Report" in out
    assert "[WARN] trades.db not found" in out


def test_post_trade_learning_cli_missing_db_exits_cleanly(tmp_path):
    code, out = _run_cli(tmp_path, "post-trade-learning", "2026-05-30")

    assert code == 1
    assert "Post-Trade Learning Report" in out
    assert "[WARN] trades.db not found" in out


def test_rollout_contract_cli_missing_db_exits_cleanly(tmp_path):
    code, out = _run_cli(tmp_path, "rollout-contract", "2026-05-30")

    assert code == 1
    assert "Rollout Contract Report" in out
    assert "[WARN] trades.db not found" in out


def test_feature_attribution_cli_empty_lifecycle_rows_warns(tmp_path):
    with sqlite3.connect(tmp_path / "trades.db") as con:
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
                canonical_intelligence_json TEXT
            )
            """
        )

    code, out = _run_cli(tmp_path, "feature-attribution", "2026-05-30")

    assert code == 1
    assert "rows_with_outcome       : 0" in out
    assert "[WARN] no lifecycle rows with realized/counterfactual outcomes" in out


def test_post_trade_learning_cli_empty_lifecycle_rows_warns(tmp_path):
    with sqlite3.connect(tmp_path / "trades.db") as con:
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
                canonical_intelligence_json TEXT
            )
            """
        )

    code, out = _run_cli(tmp_path, "post-trade-learning", "2026-05-30")

    assert code == 1
    assert "rows" in out and ": 0" in out
    assert "[WARN] no lifecycle rows found" in out


def test_rollout_contract_cli_empty_lifecycle_rows_warns(tmp_path):
    with sqlite3.connect(tmp_path / "trades.db") as con:
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
                canonical_intelligence_json TEXT
            )
            """
        )

    code, out = _run_cli(tmp_path, "rollout-contract", "2026-05-30")

    assert code == 1
    assert "report_version          : rollout_contract_v1" in out
    assert "[WARN] no lifecycle rows with realized/counterfactual outcomes" in out


def test_rollout_contract_cli_golden_fixture_locks_report_contract(tmp_path):
    _create_lifecycle_fixture_db(tmp_path)

    code, out = _run_cli(
        tmp_path,
        "rollout-contract",
        "2026-05-30",
        "--min-sample-size",
        "1",
    )

    assert code == 0
    assert "Rollout Contract Report - 2026-05-30" in out
    assert "report_version          : rollout_contract_v1" in out
    assert "runtime_effect          : telemetry_only_no_live_authority" in out
    assert "family_cap" in out
    assert "portfolio_decision" in out
    assert "narrow_block_candidate" in out
    assert "execution_quality" in out
    assert "size_down_candidate" in out
    assert "market_regime" in out
    assert "observe_only" in out
    assert "capped_by:" in out


def main():
    tests = [
        test_feature_attribution_cli_missing_db_exits_cleanly,
        test_post_trade_learning_cli_missing_db_exits_cleanly,
        test_rollout_contract_cli_missing_db_exits_cleanly,
        test_feature_attribution_cli_empty_lifecycle_rows_warns,
        test_post_trade_learning_cli_empty_lifecycle_rows_warns,
        test_rollout_contract_cli_empty_lifecycle_rows_warns,
        test_rollout_contract_cli_golden_fixture_locks_report_contract,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ops check CLI tests passed.")


if __name__ == "__main__":
    main()
