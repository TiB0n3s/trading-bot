#!/usr/bin/env python3
"""
Run targeted trading-bot tests.

Usage:
  python3 scripts/run_tests.py
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path("/etc/trading-bot.env")
VENV_PYTHON = ROOT / "venv" / "bin" / "python"


def reexec_under_venv_if_available():
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


def load_env_file(path=ENV_FILE):
    if not path.exists():
        return False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value

    return True


def child_test_env():
    paths = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "src")]
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        paths.append(existing)

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


TESTS = [
    "tests/test_market_time.py",
    "tests/test_rejection_categories.py",
    "tests/test_rejection_category_registry.py",
    "tests/test_symbols_config.py",
    "tests/test_cron_contract.py",
    "tests/test_moved_script_references.py",
    "tests/test_config_factories.py",
    "tests/test_auto_buy_manager.py",
    "tests/test_intraday_trade_feedback_service.py",
    "tests/test_market_context_schema.py",
    "tests/test_setup_policy.py",
    "tests/test_setup_engine_service.py",
    "tests/test_setup_structure_service.py",
    "tests/test_market_regime_service.py",
    "tests/test_market_microstructure_service.py",
    "tests/test_market_participation_service.py",
    "tests/test_volatility_normalization_service.py",
    "tests/test_downside_asymmetry_service.py",
    "tests/test_exit_decision_quality_service.py",
    "tests/test_news_event_model.py",
    "tests/test_source_reliability.py",
    "tests/test_context_symbol_events.py",
    "tests/test_hard_blocker_taxonomy.py",
    "tests/test_rollout_contract_service.py",
    "tests/test_confidence_calibration_service.py",
    "tests/test_portfolio_decision_service.py",
    "tests/test_execution_quality_service.py",
    "tests/test_slippage_kelly_sizing_service.py",
    "tests/test_decision_policy.py",
    "tests/test_decision_utility_service.py",
    "tests/test_analytics_method_service.py",
    "tests/test_portfolio_ai_toolkit_service.py",
    "tests/test_technical_feature_engineering_service.py",
    "tests/test_regime_switching_service.py",
    "tests/test_regime_switching_service_extended.py",
    "tests/test_regime_model_router_service.py",
    "tests/test_regime_observation_service.py",
    "tests/test_regime_circuit_breaker_service.py",
    "tests/test_regime_rebuilder_service.py",
    "tests/test_async_ai_pipeline_architecture_service.py",
    "tests/test_regime_risk_protocol_service.py",
    "tests/test_optional_dependency_service.py",
    "tests/test_vm_resource_readiness_service.py",
    "tests/test_trading_education_corpus_service.py",
    "tests/test_persistent_lockout_service.py",
    "tests/test_financial_sentiment_service.py",
    "tests/test_ai_event_context_service.py",
    "tests/test_event_collection_ai_backfill.py",
    "tests/test_ai_momentum_pattern_service.py",
    "tests/test_ai_review_suite_service.py",
    "tests/test_supervised_prediction_training_service.py",
    "tests/test_supervised_prediction_training_repo.py",
    "tests/test_advanced_alpha_model_comparison_service.py",
    "tests/test_friction_heatmap_service.py",
    "tests/test_advanced_alpha_readiness_service.py",
    "tests/test_shadow_prediction_service.py",
    "tests/test_timescale_tick_writer_service.py",
    "tests/test_dashboard_alert_service.py",
    "tests/test_decision_context.py",
    "tests/test_ml_authority.py",
    "tests/test_strategy_memory.py",
    "tests/test_prediction_cache_service.py",
    "tests/test_prediction_cache.py",
    "tests/test_market_data_service.py",
    "tests/test_polygon_market_data_service.py",
    "tests/test_market_data_parity_service.py",
    "tests/test_research_export_service.py",
    "tests/test_sec_edgar_service.py",
    "tests/test_rejected_signal_outcomes.py",
    "tests/test_symbol_momentum_timing_service.py",
    "tests/test_label_v1_builder.py",
    "tests/test_export_ml_dataset.py",
    "tests/test_feature_parity_contract.py",
    "tests/test_candidate_universe_service.py",
    "tests/test_candidate_outcome_coverage_service.py",
    "tests/test_candidate_outcome_backfill_service.py",
    "tests/test_ml_replay.py",
    "tests/test_policy_artifacts.py",
    "tests/test_decision_snapshot_service.py",
    "tests/test_canonical_intelligence_service.py",
    "tests/test_symbol_pattern_backfill_service.py",
    "tests/test_symbol_pattern_outcome_service.py",
    "tests/test_symbol_universe_retraining_service.py",
    "tests/test_symbol_universe_retrain_pipeline.py",
    "tests/test_external_symbol_candidate_service.py",
    "tests/test_external_symbol_candidate_refresh_pipeline.py",
    "tests/test_pattern_learning_inputs_service.py",
    "tests/test_bar_pattern_feature_service.py",
    "tests/test_historical_bar_archive_service.py",
    "tests/test_historical_bar_archive_pipeline.py",
    "tests/test_historical_bar_backfill_pipeline.py",
    "tests/test_historical_bar_completion_hook.py",
    "tests/test_polygon_tick_archive_pipeline.py",
    "tests/test_historical_bar_coverage_checks.py",
    "tests/test_historical_bar_progress_checks.py",
    "tests/test_historical_bar_readiness_checks.py",
    "tests/test_historical_bar_model_intelligence_service.py",
    "tests/test_historical_bar_paper_strategy_service.py",
    "tests/test_historical_bar_meta_label_authority_service.py",
    "tests/test_alternative_data_gate_service.py",
    "tests/test_concept_drift_service.py",
    "tests/test_counterfactual_learning_service.py",
    "tests/test_cross_layer_verification_service.py",
    "tests/test_layered_model_decision_service.py",
    "tests/test_historical_bar_retry_missing.py",
    "tests/test_external_symbol_discovery_checks.py",
    "tests/test_ml_dataset_export_checks.py",
    "tests/test_canonical_exit_service.py",
    "tests/test_exit_snapshot_backfill_service.py",
    "tests/test_lifecycle_analysis_service.py",
    "tests/test_lifecycle_dashboard_service.py",
    "tests/test_calibration_bucket_service.py",
    "tests/test_post_trade_learning_service.py",
    "tests/test_feature_attribution_service.py",
    "tests/test_point_in_time_archive_service.py",
    "tests/test_decision_snapshots.py",
    "tests/test_bot_events_service.py",
    "tests/test_job_runs_service.py",
    "tests/test_retention_policy.py",
    "tests/test_broker.py",
    "tests/test_db_migrations.py",
    "tests/test_fill_stream.py",
    "tests/test_live_bar_stream_service.py",
    "tests/test_fill_poller_service.py",
    "tests/test_trend.py",
    "tests/test_fast_lane.py",
    "tests/test_fast_lane_sell.py",
    "tests/test_position_manager.py",
    "tests/test_trade_matcher.py",
    "tests/test_trade_matcher_service.py",
    "tests/test_trade_accounting.py",
    "tests/test_live_bias_override.py",
    "tests/test_app_phase0.py",
    "tests/test_startup_service.py",
    "tests/test_runtime_state_services.py",
    "tests/test_momentum_service.py",
    "tests/test_live_features_cli.py",
    "tests/test_live_features_service.py",
    "tests/test_live_label_bar_contract.py",
    "tests/test_pre_market_research_service.py",
    "tests/test_prior_session_context_service.py",
    "tests/test_session_momentum_service.py",
    "tests/test_ledger_repo.py",
    "tests/test_daily_summary_service.py",
    "tests/test_excursion_service.py",
    "tests/test_entry_quality_service.py",
    "tests/test_filter_report_service.py",
    "tests/test_prediction_validation_service.py",
    "tests/test_prediction_drift_service.py",
    "tests/test_ml_promotion.py",
    "tests/test_pipeline_retrain.py",
    "tests/test_after_close_learning_pipeline.py",
    "tests/test_post_session_review_pipeline.py",
    "tests/test_clean_local_artifacts_script.py",
    "tests/test_blocked_signal_outcome_service.py",
    "tests/test_missed_opportunity_service.py",
    "tests/test_ops_check_services.py",
    "tests/test_ops_check_cli.py",
    "tests/test_architecture_boundaries.py",
    "tests/test_process_signal_rejections.py",
    "tests/test_signal_pipeline.py",
    "tests/test_preflight_service.py",
    "tests/test_signal_stage_guards.py",
    "tests/test_context_approval_sizing_services.py",
    "tests/test_sizing_ownership.py",
    "tests/test_execution_service.py",
    "tests/test_execution_adapters.py",
    "tests/test_portfolio_rotation_service.py",
    "tests/test_trade_audit_service.py",
    "tests/test_live_signal_characterization.py",
    "tests/test_phase7_observability.py",
    "tests/test_macro_risk.py",
    "tests/test_pnl.py",
]


def main():
    reexec_under_venv_if_available()
    env_loaded = load_env_file()

    print("=" * 64)
    print("  Trading Bot Targeted Tests")
    print("=" * 64)
    print(f"env_file_loaded={env_loaded}")

    failures = 0

    for test in TESTS:
        print()
        print("──", test, "─" * max(0, 56 - len(test)))
        result = subprocess.run([sys.executable, test], cwd=ROOT, env=child_test_env())
        if result.returncode != 0:
            failures += 1

    print()
    print("=" * 64)
    if failures:
        print(f"[FAIL] {failures} test file(s) failed")
        return 1

    print(f"[OK] all {len(TESTS)} test file(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
