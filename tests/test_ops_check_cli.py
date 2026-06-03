#!/usr/bin/env python3
"""Lightweight tests for ops_check.py command routing."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ops_check
from repositories import auto_buy_repo


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
    policy_decision="allow",
    policy_enforced=False,
    policy_size_effect="none",
    policy_execution_effect="none",
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
            "momentum_state": {
                "direction": "bullish" if regime != "risk_off_unwind" else "bearish",
                "state": "accelerating" if regime == "trend_expansion" else "mixed",
                "session_label": "uptrend" if regime != "risk_off_unwind" else "fading",
            },
            "prediction_state": {
                "ml_score": 62 if regime != "risk_off_unwind" else 38,
                "ml_bucket": "high_55_plus" if regime != "risk_off_unwind" else "weak_below_45",
                "ml_sample_size": 80,
                "runtime_effect": "observe_only_compare",
            },
            "advisory_authority_state": {
                "utility_estimate": {"utility_decision": utility},
                "decision_policy_outcome": {
                    "advisory_decision": policy_decision,
                    "authority_mode": "paper_only",
                    "enforced": policy_enforced,
                    "effect_on_size": policy_size_effect,
                    "effect_on_execution": policy_execution_effect,
                    "reason": f"fixture policy {policy_decision}",
                },
            },
            "pattern_state": {
                "pattern_label": (
                    "trend_continuation_with_participation"
                    if regime in {"trend_expansion", "orderly_pullback"}
                    else "momentum_deterioration"
                ),
                "directional_bias": (
                    "constructive"
                    if regime in {"trend_expansion", "orderly_pullback"}
                    else "risk_negative"
                ),
                "confidence_quality": "uncalibrated_prior",
                "runtime_effect": "observe_only_no_live_authority",
                "source": "canonical_pattern_state",
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
                    policy_decision="size_down",
                    policy_enforced=True,
                    policy_size_effect="size_down",
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
                    policy_decision="block",
                    policy_enforced=False,
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


def test_symbol_patterns_cli_missing_db_exits_cleanly(tmp_path):
    code, out = _run_cli(tmp_path, "symbol-patterns", "2026-05-30")

    assert code == 1
    assert "Symbol Pattern Outcomes" in out
    assert "[WARN] trades.db not found" in out


def test_bar_pattern_backfill_cli_missing_db_exits_cleanly(tmp_path):
    code, out = _run_cli(tmp_path, "bar-pattern-backfill", "2026-05-30", "--symbol", "AAPL")

    assert code == 1
    assert "EFI/PVT Bar Pattern Backfill" in out
    assert "[WARN] trades.db not found" in out


def test_ops_reliability_cli_missing_db_exits_cleanly(tmp_path):
    for command, title, version in (
        ("event-source-coverage", "Event Source Coverage", "event_source_coverage_v1"),
        ("event-context-validation", "Event Context Validation", "event_context_validation_v1"),
        ("context-freshness", "Context Freshness", "context_freshness_v1"),
        ("data-freshness-gate", "Data Freshness Gate", "data_freshness_gate_v1"),
        ("portfolio-risk", "Portfolio Risk Report", "portfolio_risk_v1"),
        ("decision-lifecycle-dashboard", "Decision Lifecycle Dashboard", None),
        ("candidate-outcome-backfill", "Candidate Outcome Backfill", None),
        ("calibration-buckets", "Calibration Buckets", None),
        ("pattern-learning-inputs", "Pattern Learning Inputs", None),
        ("signal-source-readiness", "Signal Source Readiness", None),
        ("learning-readiness", "Learning Readiness", None),
        ("ai-intelligence-review", "AI Intelligence Integration Review", "ai_intelligence_review_v1"),
    ):
        code, out = _run_cli(tmp_path, command, "2026-05-30")
        assert code == 1
        assert title in out
        if version:
            assert f"report_version          : {version}" in out
        assert "[WARN] trades.db not found" in out


def test_signal_source_readiness_cli_flags_legacy_source_gate(tmp_path):
    db_path = tmp_path / "trades.db"
    auto_buy_repo.init_tables(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO auto_buy_candidates (
                timestamp, symbol, signal_source, decision, score, reason,
                live_buy_enabled, order_submitted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-05-30T10:00:00-04:00",
                "AAPL",
                "tradingview_alert",
                "strong_buy_candidate",
                17.0,
                "test",
                1,
                0,
            ),
        )
        con.execute(
            """
            INSERT INTO auto_buy_decision_snapshots (
                created_at, candidate_timestamp, symbol, signal_source, decision,
                score, live_buy_enabled, live_block_reason, order_submitted,
                runtime_effect
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-05-30T10:00:01-04:00",
                "2026-05-30T10:00:00-04:00",
                "AAPL",
                "tradingview_alert",
                "strong_buy_candidate",
                17.0,
                1,
                "tradingview alert symbol requires webhook approval path",
                0,
                "auto_buy_paper_execution_path",
            ),
        )

    old_mode = os.environ.get("AUTO_BUY_SIGNAL_MODE")
    old_deprecated = os.environ.get("TRADINGVIEW_ALERTS_DEPRECATED")
    old_allow = os.environ.get("AUTO_BUY_ALLOW_TRADINGVIEW_LIVE")
    try:
        os.environ["AUTO_BUY_SIGNAL_MODE"] = "legacy_source_gate"
        os.environ["TRADINGVIEW_ALERTS_DEPRECATED"] = "false"
        os.environ["AUTO_BUY_ALLOW_TRADINGVIEW_LIVE"] = "false"
        code, out = _run_cli(tmp_path, "signal-source-readiness", "2026-05-30")
    finally:
        for key, old_value in (
            ("AUTO_BUY_SIGNAL_MODE", old_mode),
            ("TRADINGVIEW_ALERTS_DEPRECATED", old_deprecated),
            ("AUTO_BUY_ALLOW_TRADINGVIEW_LIVE", old_allow),
        ):
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value

    assert code == 1
    assert "Signal Source Readiness" in out
    assert "legacy-tv strong candidates" in out
    assert "tradingview alert symbol requires webhook approval path" in out
    assert "Set AUTO_BUY_SIGNAL_MODE=internal_all" in out


def test_signal_source_readiness_cli_passes_when_internal_all_active(tmp_path):
    db_path = tmp_path / "trades.db"
    auto_buy_repo.init_tables(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO auto_buy_candidates (
                timestamp, symbol, signal_source, decision, score, reason,
                live_buy_enabled, order_submitted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-05-30T10:00:00-04:00",
                "AAPL",
                "tradingview_alert",
                "strong_buy_candidate",
                17.0,
                "test",
                1,
                0,
            ),
        )

    old_mode = os.environ.get("AUTO_BUY_SIGNAL_MODE")
    old_deprecated = os.environ.get("TRADINGVIEW_ALERTS_DEPRECATED")
    try:
        os.environ["AUTO_BUY_SIGNAL_MODE"] = "internal_all"
        os.environ["TRADINGVIEW_ALERTS_DEPRECATED"] = "false"
        code, out = _run_cli(tmp_path, "signal-source-readiness", "2026-05-30")
    finally:
        for key, old_value in (
            ("AUTO_BUY_SIGNAL_MODE", old_mode),
            ("TRADINGVIEW_ALERTS_DEPRECATED", old_deprecated),
        ):
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value

    assert code == 0
    assert "internal all-symbol execution     true" in out
    assert "[OK] signal-source readiness check completed" in out


def test_resource_readiness_cli_does_not_require_db(tmp_path):
    code, out = _run_cli(tmp_path, "resource-readiness", "2026-05-30")

    assert code == 0
    assert "VM Resource Readiness" in out
    assert "report_version          : vm_resource_readiness_v1" in out
    assert "runtime_effect          : readiness_only_no_live_authority" in out
    assert "polygon_market_data" in out
    assert "sec_edgar_official_disclosures" in out


def test_market_data_parity_cli_requires_symbol(tmp_path):
    code, out = _run_cli(tmp_path, "market-data-parity")

    assert code == 1
    assert "Market Data Parity - UNKNOWN" in out
    assert "[WARN] symbol is required" in out


def test_market_data_parity_bars_cli_requires_date(tmp_path):
    code, out = _run_cli(tmp_path, "market-data-parity", "AAPL", "--bars")

    assert code == 1
    assert "Market Data Parity - AAPL" in out
    assert "[WARN] --date is required for --bars mode" in out


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


def test_symbol_patterns_cli_golden_fixture_locks_report_contract(tmp_path):
    _create_lifecycle_fixture_db(tmp_path)

    code, out = _run_cli(
        tmp_path,
        "symbol-patterns",
        "2026-05-30",
        "--min-sample-size",
        "1",
    )

    assert code == 0
    assert "Symbol Pattern Outcomes - 2026-05-30" in out
    assert "report_version          : symbol_pattern_outcomes_v1" in out
    assert "runtime_effect          : diagnostic_only_no_live_authority" in out
    assert "Pattern outcomes" in out
    assert "trend_continuation_with_participation" in out
    assert "momentum_deterioration" in out
    assert "Rollout governance" in out
    assert "[OK] symbol pattern diagnostics completed; no live authority changed" in out


def test_pattern_learning_inputs_cli_uses_trade_and_candidate_rows(tmp_path):
    with sqlite3.connect(tmp_path / "trades.db") as con:
        con.execute(
            """
            CREATE TABLE matched_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                entry_timestamp TEXT,
                exit_timestamp TEXT,
                realized_pnl_pct REAL,
                realized_pnl REAL,
                won INTEGER,
                holding_minutes REAL,
                mfe_pct REAL,
                capture_ratio REAL,
                setup_label TEXT,
                setup_policy_action TEXT,
                ml_prediction_bucket TEXT,
                ml_prediction_score REAL,
                session_trend_label TEXT,
                buy_opportunity_recommendation TEXT,
                exit_reason TEXT,
                entry_source TEXT,
                signal_source TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO matched_trades (
                symbol, entry_timestamp, exit_timestamp, realized_pnl_pct,
                realized_pnl, won, holding_minutes, mfe_pct, capture_ratio,
                setup_label, setup_policy_action, ml_prediction_bucket,
                ml_prediction_score, session_trend_label,
                buy_opportunity_recommendation, exit_reason
            ) VALUES (
                'AAPL', '2026-05-30T10:00:00', '2026-05-30T10:30:00',
                0.8, 4.2, 1, 30, 1.2, 0.67, 'breakout', 'neutral',
                'high_55_plus', 61, 'strong_uptrend',
                'strong_buy_candidate', 'position_manager_full_exit'
            )
            """
        )
        con.execute(
            """
            CREATE TABLE candidate_universe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_ts TEXT,
                symbol TEXT,
                action TEXT,
                candidate_kind TEXT,
                candidate_status TEXT,
                score REAL,
                threshold REAL,
                threshold_distance REAL,
                decision TEXT,
                reason TEXT,
                source TEXT,
                setup_label TEXT,
                regime TEXT,
                session_phase TEXT,
                candidate_json TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO candidate_universe (
                candidate_ts, symbol, action, candidate_kind, candidate_status,
                score, threshold, threshold_distance, decision, reason, source,
                setup_label, regime, session_phase, candidate_json
            ) VALUES (
                '2026-05-30T10:05:00', 'NVDA', 'buy', 'entry',
                'near_threshold', 72, 75, -3, 'skip', 'below threshold',
                'auto_buy', 'breakout', 'trend_expansion', 'first_30m',
                '{"forward_mfe_pct": 1.4, "forward_return_pct": 0.7, "symbol_pattern": "trend_continuation_with_participation"}'
            )
            """
        )
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT,
                pattern_label TEXT,
                pattern_score REAL,
                opportunity_action TEXT,
                opportunity_quality TEXT,
                long_opportunity_score REAL,
                sell_opportunity_score REAL,
                forward_return_pct REAL,
                forward_mfe_pct REAL,
                forward_mae_pct REAL,
                horizon_bars INTEGER,
                feature_version TEXT,
                runtime_effect TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO bar_pattern_features (
                symbol, bar_timestamp, timeframe, pattern_label, pattern_score,
                opportunity_action, opportunity_quality,
                long_opportunity_score, sell_opportunity_score,
                forward_return_pct, forward_mfe_pct, forward_mae_pct,
                horizon_bars, feature_version, runtime_effect
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "AAPL",
                    "2026-05-30T10:10:00",
                    "5m",
                    "efi_pvt_breakout_confirmation",
                    74.0,
                    "long_candidate",
                    "best_buy_window",
                    82.5,
                    10.0,
                    0.9,
                    1.6,
                    -0.1,
                    12,
                    "efi_pvt_bar_pattern_v1",
                    "observe_only_pattern_learning_no_live_authority",
                ),
                (
                    "AAPL",
                    "2026-05-30T11:20:00",
                    "5m",
                    "efi_fading_pvt_flat",
                    42.0,
                    "sell_or_avoid_candidate",
                    "risk_window",
                    12.0,
                    75.0,
                    -0.4,
                    0.1,
                    -0.8,
                    12,
                    "efi_pvt_bar_pattern_v1",
                    "observe_only_pattern_learning_no_live_authority",
                ),
            ],
        )

    code, out = _run_cli(tmp_path, "pattern-learning-inputs", "2026-05-30")

    assert code == 0
    assert "Pattern Learning Inputs - 2026-05-30" in out
    assert "report_version                      : pattern_learning_inputs_v1" in out
    assert "runtime_effect                      : diagnostic_only_no_live_authority" in out
    assert "fully_integrated_pattern_outcomes : 1 (100.0%)" in out
    assert "good_buy_good_sell" in out
    assert "rows_with_forward_outcome         : 1 (100.0%)" in out
    assert "EFI/PVT bar-pattern strategy evidence" in out
    assert "bar_pattern_rows                  : 2" in out
    assert "long_candidate|best_buy_window" in out
    assert "sell_or_avoid_candidate|risk_window" in out
    assert "Top EFI/PVT buy windows" in out
    assert "Top EFI/PVT sell-or-avoid windows" in out
    assert "[OK] pattern learning inputs summarized; no live authority changed" in out


def test_ai_intelligence_review_cli_golden_fixture_covers_ten_recommendations(tmp_path):
    _create_lifecycle_fixture_db(tmp_path)

    code, out = _run_cli(tmp_path, "ai-intelligence-review", "2026-05-30")

    assert code == 0
    assert "AI Intelligence Integration Review - 2026-05-30" in out
    assert "report_version          : ai_intelligence_review_v1" in out
    assert "ai_review_version       : ai_review_suite_v1" in out
    assert "runtime_effect          : observe_only_no_live_authority" in out
    assert "authority               : review_only_no_trade_authority" in out
    for label in (
        "1. Context interpreter",
        "2. Pattern summarizer",
        "3. Disagreement reviewer",
        "4. Post-trade analyst",
        "5. Governance assistant",
        "6. Source reliability auditor",
        "7. Candidate-universe reviewer",
        "8. Explicit AI contract",
        "9. Promotion path reviewer",
        "10. Practical integration tasks",
    ):
        assert label in out
    assert "[OK] AI intelligence review completed; no live authority changed" in out


def test_lifecycle_dashboard_and_calibration_cli_use_lifecycle_rows(tmp_path):
    _create_lifecycle_fixture_db(tmp_path)

    code, out = _run_cli(tmp_path, "decision-lifecycle-dashboard", "2026-05-30", "--samples", "2")
    assert code == 0
    assert "Decision Lifecycle Dashboard" in out
    assert "report_version                 : lifecycle_dashboard_v1" in out
    assert "Top rejected rows by forward MFE" in out

    code, out = _run_cli(tmp_path, "calibration-buckets", "2026-05-30", "--min-sample-size", "1")
    assert code == 0
    assert "Calibration Buckets" in out
    assert "report_version          : calibration_buckets_v1" in out
    assert "setup=" in out


def test_research_export_cli_writes_daily_manifest(tmp_path):
    try:
        import duckdb  # noqa: F401
        import pyarrow  # noqa: F401
    except Exception:
        print("skipping: duckdb/pyarrow unavailable")
        return

    with sqlite3.connect(tmp_path / "trades.db") as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_time TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER
            )
            """
        )
        con.execute(
            """
            INSERT INTO decision_snapshots (decision_time, symbol, action, approved)
            VALUES (?, ?, ?, ?)
            """,
            ("2026-06-02T10:00:00+00:00", "AAPL", "buy", 1),
        )

    code, out = _run_cli(tmp_path, "research-export", "2026-06-02")

    assert code == 0
    assert "Research Export" in out
    assert "research_export_v1" in out
    assert "[OK] research export complete" in out
    assert (tmp_path / "research_exports" / "2026-06-02" / "manifest.json").exists()


def test_learning_readiness_cli_golden_fixture_summarizes_holistic_evidence(tmp_path):
    _create_lifecycle_fixture_db(tmp_path)
    (tmp_path / "strategy_memory.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-30 16:30:00",
                "trade_count": 12,
                "setup_label_context": {"late_chase": {"recommendation": "caution"}},
                "prediction_decision_context": {"block": {"recommendation": "avoid"}},
                "buy_opportunity_context": {"watch": {"recommendation": "caution"}},
                "session_trend_context": {"fading": {"recommendation": "avoid"}},
            },
            sort_keys=True,
        )
    )
    with sqlite3.connect(tmp_path / "trades.db") as con:
        con.execute(
            """
            CREATE TABLE job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_sec REAL NOT NULL,
                exit_code INTEGER,
                lock_acquired INTEGER NOT NULL,
                skipped_reason TEXT,
                rows_written INTEGER,
                warnings_count INTEGER,
                artifact_path TEXT,
                artifact_hash TEXT,
                command TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO job_runs (
                job_name, started_at, finished_at, duration_sec, exit_code,
                lock_acquired, rows_written, warnings_count, command
            ) VALUES (?, ?, ?, ?, 0, 1, ?, 0, ?)
            """,
            [
                (
                    "live_features",
                    "2026-05-30T09:30:00+00:00",
                    "2026-05-30T09:30:05+00:00",
                    5.0,
                    4,
                    "job_runner live_features",
                ),
                (
                    "candidate_universe",
                    "2026-05-30T16:05:00+00:00",
                    "2026-05-30T16:05:02+00:00",
                    2.0,
                    4,
                    "job_runner candidate_universe",
                ),
            ],
        )
        con.execute(
            """
            CREATE TABLE candidate_universe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                candidate_ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                candidate_kind TEXT NOT NULL,
                candidate_status TEXT NOT NULL,
                score REAL,
                threshold REAL,
                threshold_distance REAL,
                decision TEXT,
                reason TEXT,
                source TEXT,
                setup_label TEXT,
                regime TEXT,
                session_phase TEXT,
                canonical_intelligence_hash TEXT,
                canonical_intelligence_version TEXT,
                candidate_json TEXT NOT NULL,
                runtime_effect TEXT NOT NULL DEFAULT 'candidate_capture_only_no_live_authority'
            )
            """
        )
        con.executemany(
            """
            INSERT INTO candidate_universe (
                created_at, candidate_ts, symbol, action, candidate_kind,
                candidate_status, score, threshold, threshold_distance,
                decision, reason, source, setup_label, regime, session_phase,
                candidate_json
            ) VALUES (?, ?, ?, 'buy', 'entry', ?, ?, 50, ?, ?, ?, ?, ?, ?, ?, '{}')
            """,
            [
                (
                    "2026-05-30T10:00:00+00:00",
                    "2026-05-30T10:00:00+00:00",
                    "AAPL",
                    "taken",
                    65,
                    15,
                    "approved",
                    "approved",
                    "auto_buy",
                    "breakout",
                    "trend_expansion",
                    "first_30m",
                ),
                (
                    "2026-05-30T10:15:00+00:00",
                    "2026-05-30T10:15:00+00:00",
                    "MSFT",
                    "near_threshold",
                    48,
                    -2,
                    "not_taken",
                    "near_threshold",
                    "auto_buy",
                    "pullback",
                    "orderly_pullback",
                    "late_morning",
                ),
            ],
        )

    code, out = _run_cli(
        tmp_path,
        "learning-readiness",
        "2026-05-30",
        "--feature-min-sample-size",
        "1",
        "--pattern-min-sample-size",
        "1",
        "--calibration-min-sample-size",
        "1",
        "--full-readiness-target",
        "4",
    )

    assert code == 0
    assert "Learning Readiness — 2026-05-30 to 2026-05-30" in out
    assert "report_version                : learning_readiness_v1" in out
    assert "runtime_effect                : diagnostic_only_no_live_authority" in out
    assert "readiness_stage               : baseline_collection" in out
    assert "sessions_with_lifecycle_rows  : 1" in out
    assert "rows_with_outcome             : 4" in out
    assert "Full readiness progress" in out
    assert "fully_integrated_outcome_rows" in out
    assert "100.00%" in out
    assert "Candidate universe" in out
    assert "near_threshold" in out
    assert "Learning effect" in out
    assert "strategy_memory_available" in out
    assert "decision_policy_size_down_enforced" in out
    assert "learning_observed_not_enforced" in out
    assert "Intelligence diagnostics" in out
    assert "[OK] learning readiness has no blockers; review manually before promotion" in out


def test_learning_effectiveness_cli_uses_readiness_payload_with_daily_framing(tmp_path):
    _create_lifecycle_fixture_db(tmp_path)
    (tmp_path / "strategy_memory.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-30 16:30:00",
                "trade_count": 12,
                "setup_label_context": {"late_chase": {"recommendation": "caution"}},
            },
            sort_keys=True,
        )
    )
    with sqlite3.connect(tmp_path / "trades.db") as con:
        con.execute(
            """
            CREATE TABLE job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_sec REAL NOT NULL,
                exit_code INTEGER,
                lock_acquired INTEGER NOT NULL,
                skipped_reason TEXT,
                rows_written INTEGER,
                warnings_count INTEGER,
                artifact_path TEXT,
                artifact_hash TEXT,
                command TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO job_runs (
                job_name, started_at, finished_at, duration_sec, exit_code,
                lock_acquired, rows_written, warnings_count, command
            ) VALUES (?, ?, ?, ?, 0, 1, ?, 0, ?)
            """,
            (
                "candidate_universe",
                "2026-05-30T16:05:00+00:00",
                "2026-05-30T16:05:02+00:00",
                2.0,
                4,
                "job_runner candidate_universe",
            ),
        )
        con.execute(
            """
            CREATE TABLE candidate_universe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                candidate_ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                candidate_kind TEXT NOT NULL,
                candidate_status TEXT NOT NULL,
                score REAL,
                threshold REAL,
                threshold_distance REAL,
                decision TEXT,
                reason TEXT,
                source TEXT,
                setup_label TEXT,
                regime TEXT,
                session_phase TEXT,
                canonical_intelligence_hash TEXT,
                canonical_intelligence_version TEXT,
                candidate_json TEXT NOT NULL,
                runtime_effect TEXT NOT NULL DEFAULT 'candidate_capture_only_no_live_authority'
            )
            """
        )
        con.execute(
            """
            INSERT INTO candidate_universe (
                created_at, candidate_ts, symbol, action, candidate_kind,
                candidate_status, score, threshold, threshold_distance,
                decision, reason, source, setup_label, regime, session_phase,
                candidate_json
            ) VALUES (?, ?, ?, 'buy', 'entry', ?, ?, 50, ?, ?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                "2026-05-30T10:00:00+00:00",
                "2026-05-30T10:00:00+00:00",
                "AAPL",
                "taken",
                65,
                15,
                "approved",
                "approved",
                "auto_buy",
                "breakout",
                "trend_expansion",
                "first_30m",
            ),
        )

    code, out = _run_cli(
        tmp_path,
        "learning-effectiveness",
        "2026-05-30",
        "--feature-min-sample-size",
        "1",
        "--pattern-min-sample-size",
        "1",
        "--calibration-min-sample-size",
        "1",
        "--full-readiness-target",
        "4",
    )

    assert code == 0
    assert "Learning Effectiveness — 2026-05-30 to 2026-05-30" in out
    assert "report_version                : learning_readiness_v1" in out
    assert "Learning effect" in out
    assert "strategy_memory_available" in out
    assert "learning_constrained_rows" in out
    assert "[OK] learning effectiveness has no blockers; review manually before promotion" in out


def test_regime_status_json_smoke(tmp_path):
    state_path = tmp_path / "regime_state.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "regime_status.py"),
            "--json",
            "--no-save",
            "--state",
            str(state_path),
            "--lockout-path",
            str(tmp_path / "risk_lockout.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "regime" in payload
    assert "routing" in payload
    assert "tranche_plan" in payload


def main():
    tests = [
        test_feature_attribution_cli_missing_db_exits_cleanly,
        test_post_trade_learning_cli_missing_db_exits_cleanly,
        test_rollout_contract_cli_missing_db_exits_cleanly,
        test_symbol_patterns_cli_missing_db_exits_cleanly,
        test_bar_pattern_backfill_cli_missing_db_exits_cleanly,
        test_ops_reliability_cli_missing_db_exits_cleanly,
        test_signal_source_readiness_cli_flags_legacy_source_gate,
        test_signal_source_readiness_cli_passes_when_internal_all_active,
        test_feature_attribution_cli_empty_lifecycle_rows_warns,
        test_post_trade_learning_cli_empty_lifecycle_rows_warns,
        test_rollout_contract_cli_empty_lifecycle_rows_warns,
        test_rollout_contract_cli_golden_fixture_locks_report_contract,
        test_symbol_patterns_cli_golden_fixture_locks_report_contract,
        test_pattern_learning_inputs_cli_uses_trade_and_candidate_rows,
        test_ai_intelligence_review_cli_golden_fixture_covers_ten_recommendations,
        test_lifecycle_dashboard_and_calibration_cli_use_lifecycle_rows,
        test_research_export_cli_writes_daily_manifest,
        test_learning_readiness_cli_golden_fixture_summarizes_holistic_evidence,
        test_learning_effectiveness_cli_uses_readiness_payload_with_daily_framing,
        test_regime_status_json_smoke,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ops check CLI tests passed.")


if __name__ == "__main__":
    main()
