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

from trading_bot.ops_checks.commands.advisory_authority_checks import run_advisory_authority_report
from trading_bot.ops_checks.commands.auto_buy_checks import run_auto_buy_health
from trading_bot.ops_checks.commands.context_freshness_checks import run_context_freshness
from trading_bot.ops_checks.commands.conviction_checks import (
    run_buy_opportunity_report,
    run_claude_context_audit,
    run_conviction_stack_report,
)
from trading_bot.ops_checks.commands.event_context_validation_checks import (
    run_event_context_validation,
)
from trading_bot.ops_checks.commands.event_source_checks import run_event_source_coverage
from trading_bot.ops_checks.commands.excursion_checks import (
    run_peak_bucket_report,
    run_winner_became_loser,
)
from trading_bot.ops_checks.commands.feature_attribution_checks import (
    run_feature_attribution_report,
)
from trading_bot.ops_checks.commands.log_ledger_checks import run_log_ledger_consistency
from trading_bot.ops_checks.commands.paper_learning_authority_checks import (
    run_paper_learning_authority_report,
)
from trading_bot.ops_checks.commands.portfolio_risk_checks import run_portfolio_risk_report
from trading_bot.ops_checks.commands.post_trade_learning_checks import (
    run_post_trade_learning_report,
)
from trading_bot.ops_checks.commands.rollout_contract_checks import run_rollout_contract_report
from trading_bot.ops_checks.commands.runtime_checks import run_runtime_health
from trading_bot.ops_checks.commands.setup_breakdown import run_setup_breakdown


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
        lambda: run_rollout_contract_report("2026-05-30", base_dir=tmp_path),
        lambda: run_event_source_coverage("2026-05-30", base_dir=tmp_path),
        lambda: run_event_context_validation("2026-05-30", base_dir=tmp_path),
        lambda: run_portfolio_risk_report("2026-05-30", base_dir=tmp_path),
        lambda: run_context_freshness("2026-05-30", base_dir=tmp_path),
        lambda: run_runtime_health("2026-05-30", base_dir=tmp_path),
    ]

    buf = io.StringIO()
    with redirect_stdout(buf):
        for func in funcs:
            assert func() is False

    out = buf.getvalue()
    assert out.count("[WARN] trades.db not found") == len(funcs)
    assert "report_version          : runtime_health_v1" in out


def test_event_source_coverage_reports_reliability_mix(tmp_path):
    db_path = tmp_path / "trades.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE daily_symbol_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_date TEXT,
                symbol TEXT,
                event_type TEXT,
                confidence TEXT,
                source TEXT,
                source_url TEXT,
                raw_json TEXT,
                created_at TEXT
            )
            """
        )
        rows = [
            (
                "2026-05-30",
                "AAPL",
                "filing",
                "high",
                "SEC",
                "https://sec.gov/x",
                {
                    "source_tier": "official",
                    "trusted_source": True,
                    "search_scope": "company_direct",
                },
            ),
            (
                "2026-05-30",
                "MSFT",
                "news",
                "medium",
                "Reuters",
                "https://reuters.com/x",
                {
                    "source_tier": "confirmed_financial_news",
                    "trusted_source": True,
                    "search_scope": "company_direct",
                },
            ),
            (
                "2026-05-30",
                "NVDA",
                "supplier",
                "low",
                "Yahoo Finance",
                "https://finance.yahoo.com/x",
                {
                    "source_tier": "medium_confidence",
                    "trusted_source": False,
                    "search_scope": "company_peripheral",
                    "peripheral_context": True,
                },
            ),
        ]
        con.executemany(
            """
            INSERT INTO daily_symbol_events (
                market_date, symbol, event_type, confidence, source, source_url, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '2026-05-30T10:00:00+00:00')
            """,
            [(a, b, c, d, e, f, json.dumps(g)) for a, b, c, d, e, f, g in rows],
        )

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert run_event_source_coverage("2026-05-30", base_dir=tmp_path) is True

    out = buf.getvalue()
    assert "Event Source Coverage" in out
    assert "report_version          : event_source_coverage_v1" in out
    assert "official" in out
    assert "top_tier" in out
    assert "peripheral" in out
    assert "trusted_source_rate" in out


def test_portfolio_risk_report_reads_canonical_portfolio_state(tmp_path):
    db_path = tmp_path / "trades.db"
    canonical = {
        "regime_state": {
            "portfolio_decision": "size_down",
            "portfolio_duplicate_risk_score": 0.62,
            "incremental_var_pct": 1.7,
            "beta_contribution_delta": 1.3,
            "crowded_theme": "semiconductors",
        },
        "advisory_authority_state": {
            "portfolio_decision": {
                "decision": "size_down",
                "duplicate_risk_score": 0.62,
                "incremental_var_pct": 1.7,
                "beta_contribution_delta": 1.3,
                "factor_overlap_score": 0.4,
                "sector_concentration_delta_pct": 12.0,
                "downside_comovement_score": 0.8,
                "crowded_theme": "semiconductors",
                "overlap_symbols": ["NVDA", "AMD"],
            }
        },
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
            ) VALUES ('2026-05-30T10:00:00+00:00', 'TSM', 'buy', 1, 'approved', NULL, '{}', ?)
            """,
            (json.dumps(canonical),),
        )

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert run_portfolio_risk_report("2026-05-30", base_dir=tmp_path) is True

    out = buf.getvalue()
    assert "Portfolio Risk Report" in out
    assert "report_version          : portfolio_risk_v1" in out
    assert "semiconductors" in out
    assert "avg_factor_overlap_score" in out
    assert "NVDA" in out


def test_log_ledger_consistency_flags_unwrapped_cron(tmp_path):
    ops_dir = tmp_path / "ops"
    ops_dir.mkdir()
    (ops_dir / "crontab.tradingbot.current.txt").write_text(
        "* * * * * cd /repo && python job_runner.py --job-name ok --lock-file /tmp/x --log-file /tmp/x.log -- echo ok\n"
        "* * * * * cd /repo && python direct_script.py\n"
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert run_log_ledger_consistency(base_dir=tmp_path) is False

    out = buf.getvalue()
    assert "report_version          : log_ledger_consistency_v1" in out
    assert "unwrapped_entries : 1" in out
    assert "direct_script.py" in out


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
            "advisory_authority_state": {"utility_estimate": {"utility_decision": utility}},
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
        assert (
            run_feature_attribution_report(
                "2026-05-30",
                base_dir=tmp_path,
                min_sample_size=1,
            )
            is True
        )
        assert run_post_trade_learning_report("2026-05-30", base_dir=tmp_path) is True
        assert (
            run_rollout_contract_report(
                "2026-05-30",
                base_dir=tmp_path,
                min_sample_size=1,
            )
            is True
        )

    out = buf.getvalue()
    assert "Feature Attribution Report" in out
    assert "report_version          : feature_attribution_v1" in out
    assert "market_regime" in out
    assert "diagnostic_only_no_live_authority" in out
    assert "Post-Trade Learning Report" in out
    assert "report_version" in out
    assert "Expectancy by setup_label" in out
    assert "Rollout Contract Report" in out
    assert "rollout_contract_v1" in out


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
    assert "report_version          : advisory_authority_v1" in out
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


def test_paper_learning_authority_report_counts_canonical_override(tmp_path):
    db_path = tmp_path / "trades.db"
    override = {
        "allowed": True,
        "reason": "paper learning authority approved strong canonical intelligence",
        "setup_score": 82,
        "buy_opportunity_score": 9.5,
        "position_size_pct": 0.5,
    }
    canonical = {
        "advisory_authority_state": {
            "paper_learning_authority_outcome": override,
        }
    }
    account_state = {
        "paper_learning_authority_override": {
            **override,
            "setup_score": 70,
            "buy_opportunity_score": 8.0,
        }
    }

    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_time TEXT,
                trade_id INTEGER,
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
                id, decision_time, trade_id, symbol, action, approved, final_decision,
                rejection_reason, account_state_json, canonical_intelligence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                10,
                "2026-06-03T15:00:00+00:00",
                99,
                "MSFT",
                "buy",
                1,
                "approved",
                None,
                json.dumps(account_state),
                json.dumps(canonical),
            ),
        )

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert run_paper_learning_authority_report("2026-06-03", base_dir=tmp_path) is True

    out = buf.getvalue()
    assert "Paper Learning Authority Report" in out
    assert "report_version          : paper_learning_authority_v1" in out
    assert "runtime_effect          : paper_only_diagnostic" in out
    assert f"  {'paper_authority_rows':<38}     1" in out
    assert f"  {'allowed_overrides':<38}     1" in out
    assert f"  {'approved_after_override':<38}     1" in out
    assert "avg_setup_score" in out
    assert "82.000" in out
    assert "MSFT" in out


def test_auto_buy_health_reports_rolling_five_day_context(tmp_path):
    db_path = tmp_path / "trades.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE auto_buy_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                signal_source TEXT,
                decision TEXT,
                score REAL,
                reason TEXT,
                market_bias TEXT,
                entry_quality TEXT,
                risk_level TEXT,
                session_trend_label TEXT,
                session_trend_score REAL,
                session_return_pct REAL,
                momentum_5m_pct REAL,
                momentum_15m_pct REAL,
                momentum_30m_pct REAL,
                distance_from_vwap_pct REAL,
                setup_label TEXT,
                setup_recommendation TEXT,
                setup_score REAL,
                hard_block_reason TEXT,
                feature_snapshot_id INTEGER,
                live_buy_enabled INTEGER,
                order_submitted INTEGER,
                order_id TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE auto_buy_decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                candidate_timestamp TEXT,
                symbol TEXT,
                signal_source TEXT,
                decision TEXT,
                score REAL,
                reason TEXT,
                hard_block_reason TEXT,
                live_buy_enabled INTEGER,
                live_block_reason TEXT,
                risk_cross_check_reason TEXT,
                order_submitted INTEGER,
                order_id TEXT,
                order_status TEXT,
                candidate_json TEXT,
                order_json TEXT,
                runtime_effect TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE auto_buy_intraday_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                target_date TEXT NOT NULL,
                symbol TEXT,
                feedback_key TEXT NOT NULL,
                status TEXT NOT NULL,
                score_penalty REAL,
                hard_block_reason TEXT,
                evidence_json TEXT,
                candidate_json TEXT,
                runtime_effect TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            INSERT INTO auto_buy_candidates (
                timestamp, symbol, signal_source, decision, score, reason,
                session_trend_label, session_trend_score, setup_label,
                live_buy_enabled, order_submitted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (
                "2026-06-04T09:45:00-04:00",
                "AAPL",
                "internal_bar_only",
                "watch",
                12.0,
                "5d_constructive:+1",
                "developing_uptrend",
                4,
                "confirmed_near_vwap_recovery",
            ),
        )
        con.execute(
            """
            INSERT INTO auto_buy_decision_snapshots (
                created_at, candidate_timestamp, symbol, signal_source, decision,
                score, reason, hard_block_reason, live_buy_enabled,
                live_block_reason, order_submitted, candidate_json, order_json,
                runtime_effect
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-06-04T09:45:01-04:00",
                "2026-06-04T09:45:00-04:00",
                "AAPL",
                "internal_bar_only",
                "watch",
                12.0,
                "5d_constructive:+1",
                "decision=watch",
                0,
                "decision=watch",
                0,
                json.dumps(
                    {
                        "five_day_return_pct": 3.2,
                        "rolling_momentum_source": "rolling_momentum_json",
                    }
                ),
                "{}",
                "auto_buy_paper_execution_path",
            ),
        )
        con.execute(
            """
            INSERT INTO auto_buy_intraday_feedback (
                created_at, target_date, symbol, feedback_key, status,
                score_penalty, hard_block_reason, evidence_json,
                candidate_json, runtime_effect
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-06-04T09:45:02-04:00",
                "2026-06-04",
                "AAPL",
                "ml=weak_below_45|setup_action=avoid",
                "block",
                -4.0,
                "intraday_pattern_feedback:test",
                json.dumps(
                    {
                        "same_day_trades": 1,
                        "historical_trades": 3,
                        "sources": [
                            "same_day_filled_trades",
                            "historical_matched_trades",
                        ],
                    }
                ),
                "{}",
                "paper_intraday_pattern_block",
            ),
        )

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert run_auto_buy_health("2026-06-04", base_dir=tmp_path) is True

    out = buf.getvalue()
    assert "Rolling 5-day context" in out
    assert "rows_with_5d                 1" in out
    assert "rolling_source_rows          1" in out
    assert "avg_5d_return_pct        3.200" in out
    assert "Intraday feedback actions" in out
    assert "rows same hist penalty" in out
    assert "ml=weak_below_45|setup_action=avoid" in out


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
        test_event_source_coverage_reports_reliability_mix,
        test_portfolio_risk_report_reads_canonical_portfolio_state,
        test_log_ledger_consistency_flags_unwrapped_cron,
        test_feature_attribution_and_post_trade_learning_reports_use_lifecycle_rows,
        test_advisory_authority_report_prefers_canonical_outcomes,
        test_paper_learning_authority_report_counts_canonical_override,
        test_auto_buy_health_reports_rolling_five_day_context,
        test_setup_breakdown_prints_prominent_fallback_health,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ops check service tests passed.")


if __name__ == "__main__":
    main()
