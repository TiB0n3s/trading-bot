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

from services.ops_checks.conviction_checks import (
    run_buy_opportunity_report,
    run_claude_context_audit,
    run_conviction_stack_report,
)
from services.ops_checks.advisory_authority_checks import run_advisory_authority_report
from services.ops_checks.feature_attribution_checks import run_feature_attribution_report
from services.ops_checks.post_trade_learning_checks import run_post_trade_learning_report
from services.ops_checks.excursion_checks import (
    run_peak_bucket_report,
    run_winner_became_loser,
)
from services.ops_checks.setup_breakdown import run_setup_breakdown


def test_ops_checks_return_false_when_db_missing(tmp_path):
    funcs = [
        lambda: run_setup_breakdown("2026-05-30", base_dir=tmp_path),
        lambda: run_peak_bucket_report("2026-05-30", base_dir=tmp_path),
        lambda: run_winner_became_loser("2026-05-30", base_dir=tmp_path),
        lambda: run_conviction_stack_report("2026-05-30", base_dir=tmp_path),
        lambda: run_buy_opportunity_report("2026-05-30", base_dir=tmp_path),
        lambda: run_claude_context_audit("2026-05-30", base_dir=tmp_path),
        lambda: run_advisory_authority_report("2026-05-30", base_dir=tmp_path),
        lambda: run_feature_attribution_report("2026-05-30", base_dir=tmp_path),
        lambda: run_post_trade_learning_report("2026-05-30", base_dir=tmp_path),
    ]

    buf = io.StringIO()
    with redirect_stdout(buf):
        for func in funcs:
            assert func() is False

    out = buf.getvalue()
    assert out.count("[WARN] trades.db not found") == len(funcs)


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
):
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


def test_feature_attribution_and_post_trade_learning_reports_use_lifecycle_rows(tmp_path):
    db_path = tmp_path / "trades.db"
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
        con.execute(
            """
            INSERT INTO decision_snapshots (
                trade_id, decision_time, symbol, action, approved, final_decision,
                rejection_reason, canonical_intelligence_json
            ) VALUES (1, '2026-05-30T10:00:00+00:00', 'AAPL', 'buy', 1, 'approved', NULL, ?)
            """,
            (_canonical_lifecycle_json(),),
        )
        con.execute(
            """
            INSERT INTO exit_snapshots (
                entry_trade_id, exit_timestamp, exit_trigger,
                realized_return_pct, mfe_pct, max_adverse_excursion_pct
            ) VALUES (1, '2026-05-30T11:00:00+00:00', 'target', 0.8, 1.2, -0.2)
            """
        )
        con.execute(
            """
            INSERT INTO decision_snapshots (
                trade_id, decision_time, symbol, action, approved, final_decision,
                rejection_reason, canonical_intelligence_json
            ) VALUES (2, '2026-05-30T12:00:00+00:00', 'MSFT', 'buy', 0, 'rejected', 'trend_confirmation', ?)
            """,
            (
                _canonical_lifecycle_json(
                    regime="compression_chop",
                    execution="size_down",
                    portfolio="size_down",
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
        )
        con.execute(
            """
            INSERT INTO rejected_signal_outcomes (
                decision_snapshot_id, return_60m, max_favorable_60m, max_adverse_60m, label_status
            ) VALUES (2, -0.4, 0.1, -0.8, 'complete')
            """
        )

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert run_feature_attribution_report(
            "2026-05-30",
            base_dir=tmp_path,
            min_sample_size=1,
        ) is True
        assert run_post_trade_learning_report("2026-05-30", base_dir=tmp_path) is True

    out = buf.getvalue()
    assert "Feature Attribution Report" in out
    assert "market_regime" in out
    assert "diagnostic_only_no_live_authority" in out
    assert "Post-Trade Learning Report" in out
    assert "Expectancy by setup_label" in out


def test_advisory_authority_report_prefers_canonical_outcomes(tmp_path):
    db_path = tmp_path / "trades.db"
    canonical = {
        "advisory_authority_state": {
            "decision_policy_outcome": {
                "advisory_decision": "block",
                "authority_mode": "observe_only",
                "enforced": False,
                "effect_on_size": "none",
                "effect_on_execution": "none",
            },
            "ml_outcome": {
                "advisory_decision": "avoid",
                "authority_mode": "observe_only_compare",
                "qualified_for_authority": True,
                "enforced": False,
                "effect_on_size": "none",
                "effect_on_execution": "none",
                "would_block_under_promoted_mode": True,
                "safety_check_passed": True,
            },
            "session_gate_outcome": {
                "advisory_decision": "block",
                "authority_mode": "observe_only",
                "enforced": False,
                "effect_on_size": "cap",
                "effect_on_execution": "none",
            },
            "setup_quality_outcome": {
                "advisory_decision": "avoid",
                "authority_mode": "advisory_context",
                "enforced": False,
                "effect_on_size": "none",
                "effect_on_execution": "none",
                "score": 30,
                "source": "setup_engine",
            },
        }
    }
    legacy_conflict = {
        "decision_policy_authority": {"authority_mode": "legacy_mode"},
        "decision_policy": {"decision": "allow"},
        "prediction_gate": {
            "ml_prediction_compare_decision": "allow",
            "ml_authority": {
                "authority_mode": "live_block",
                "qualified_for_authority": False,
                "enforced": True,
            },
        },
        "session_momentum_gate": {"would_block": False, "severity": "pass"},
        "setup_quality": {"recommendation": "buy", "score": 90, "source": "legacy"},
    }

    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_time TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                final_decision TEXT,
                rejection_reason TEXT,
                account_state_json TEXT,
                canonical_intelligence_json TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO decision_snapshots (
                decision_time, symbol, action, approved, final_decision,
                rejection_reason, account_state_json, canonical_intelligence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-05-30T10:00:00+00:00",
                "AAPL",
                "buy",
                1,
                "approved",
                None,
                json.dumps(legacy_conflict),
                json.dumps(canonical),
            ),
        )

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert run_advisory_authority_report("2026-05-30", base_dir=tmp_path) is True

    out = buf.getvalue()
    for key in (
        "decision_policy_block_advisory",
        "decision_policy_block_but_approved",
        "ml_authority_qualified",
        "ml_negative_compare_would_block_under_promoted_mode",
        "ml_authority_not_enforced_due_to_mode",
        "session_would_block_but_approved",
        "weak_setup_quality_but_approved",
    ):
        assert f"  {key:<42}     1" in out
    old_counter_name = "ml_negative_compare_" + "would_block_" + "promoted"
    assert old_counter_name not in out
    assert "legacy_mode" not in out


def test_setup_breakdown_prints_prominent_fallback_health(tmp_path):
    db_path = tmp_path / "trades.db"

    def canonical(source):
        return json.dumps(
            {
                "advisory_authority_state": {
                    "setup_quality_outcome": {
                        "advisory_decision": "buy",
                        "source": source,
                        "score": 70,
                    }
                }
            }
        )

    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE trades (
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                setup_policy_action TEXT,
                setup_policy_reason TEXT,
                setup_unknown_reason TEXT,
                ml_prediction_bucket TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE matched_trades (
                entry_timestamp TEXT,
                exit_timestamp TEXT,
                symbol TEXT,
                setup_policy_action TEXT,
                setup_policy_reason TEXT,
                setup_unknown_reason TEXT,
                realized_pnl_pct REAL,
                won INTEGER,
                holding_minutes REAL,
                ml_prediction_bucket TEXT,
                exit_reason TEXT,
                mfe_pct REAL,
                capture_ratio REAL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_time TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                final_decision TEXT,
                rejection_reason TEXT,
                account_state_json TEXT,
                canonical_intelligence_json TEXT
            )
            """
        )
        for symbol, source in (
            ("AAPL", "setup_engine"),
            ("MSFT", "feature_snapshot"),
            ("NVDA", "setup_error"),
            ("TSLA", "unknown"),
        ):
            con.execute(
                """
                INSERT INTO trades (
                    timestamp, symbol, action, approved, setup_policy_action,
                    setup_policy_reason, setup_unknown_reason, ml_prediction_bucket
                ) VALUES (?, ?, 'buy', 0, 'neutral', NULL, NULL, 'unknown')
                """,
                ("2026-05-30T10:00:00+00:00", symbol),
            )
            con.execute(
                """
                INSERT INTO decision_snapshots (
                    decision_time, symbol, action, approved, final_decision,
                    rejection_reason, account_state_json, canonical_intelligence_json
                ) VALUES (?, ?, 'buy', 0, 'rejected', NULL, '{}', ?)
                """,
                ("2026-05-30T10:00:00+00:00", symbol, canonical(source)),
            )

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert run_setup_breakdown("2026-05-30", base_dir=tmp_path) is True

    out = buf.getvalue()
    assert "Setup quality fallback health" in out
    assert "fallback_count             : 3" in out
    assert "fallback_rate              : 75.0%" in out
    assert "[WARN] setup_quality fallback degradation detected" in out
    assert "setup_error" in out
    assert "feature_snapshot_fallback" in out
    assert "unknown" in out


def main():
    tests = [
        test_ops_checks_return_false_when_db_missing,
        test_feature_attribution_and_post_trade_learning_reports_use_lifecycle_rows,
        test_advisory_authority_report_prefers_canonical_outcomes,
        test_setup_breakdown_prints_prominent_fallback_health,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ops check service tests passed.")


if __name__ == "__main__":
    main()
