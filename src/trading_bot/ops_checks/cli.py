#!/usr/bin/env python3
"""
Operator check wrapper.

Usage:
  python3 ops_check.py morning
  python3 ops_check.py positions
  python3 ops_check.py alignment
  python3 ops_check.py adaptive
  python3 ops_check.py filters
  python3 ops_check.py drawdown
  python3 ops_check.py post
  python3 ops_check.py intelligence
  python3 ops_check.py events
  python3 ops_check.py context
  python3 ops_check.py learning
  python3 ops_check.py predictions
  python3 ops_check.py signal-lessons
  python3 ops_check.py trends
  python3 ops_check.py prediction-validation
  python3 ops_check.py shadow-predictions
  python3 ops_check.py bot-events
  python3 ops_check.py event-attribution
  python3 ops_check.py premarket
  python3 ops_check.py market-context-check
  python3 ops_check.py intelligence-summary
  python3 ops_check.py dataset-health
  python3 ops_check.py feature-health
  python3 ops_check.py feature-watch
  python3 ops_check.py live-bar-pattern-capture [YYYY-MM-DD]
  python3 ops_check.py rejection-summary
  python3 ops_check.py rejected-outcomes
  python3 ops_check.py auto-buy
  python3 ops_check.py signal-source-readiness
  python3 ops_check.py auto-buy-outcomes
  python3 ops_check.py decision-snapshots
  python3 ops_check.py policy-artifacts
  python3 ops_check.py retention
  python3 ops_check.py order-health
  python3 ops_check.py runtime-health
  python3 ops_check.py runtime-health-trend START_DATE END_DATE
  python3 ops_check.py observability-health [YYYY-MM-DD]
  python3 ops_check.py context-freshness
  python3 ops_check.py data-freshness-gate
  python3 ops_check.py event-source-coverage
  python3 ops_check.py event-context-validation
  python3 ops_check.py external-symbol-discovery [START_DATE] [--end-date YYYY-MM-DD] [--min-mentions N]
  python3 ops_check.py external-symbol-candidates
  python3 ops_check.py log-ledger-consistency
  python3 ops_check.py portfolio-risk
  python3 ops_check.py production-evidence
  python3 ops_check.py config-audit
  python3 ops_check.py feature-flags [--limit N]
  python3 ops_check.py model-governance [--min-rows N] [--min-symbols N] [--min-accuracy F]
  python3 ops_check.py secrets-hygiene [--env-file PATH]
  python3 ops_check.py architecture-surface
  python3 ops_check.py database-backups
  python3 ops_check.py local-load-probe [--requests N] [--concurrency N] [--symbol AAPL] [--action buy]
  python3 ops_check.py paper-replay-load-probe [--requests N] [--concurrency N] [--symbol AAPL] [--action buy]
  python3 ops_check.py full-session-paper-replay [--symbols AAPL,MSFT] [--execute] [--max-requests N]
  python3 ops_check.py incident-workflow --title "brief title" [--severity low|medium|high|critical] [--create]
  python3 ops_check.py incident-escalation-readiness
  python3 ops_check.py external-observability-readiness
  python3 ops_check.py secrets-manager-readiness
  python3 ops_check.py feature-flag-change-history
  python3 ops_check.py feature-flag-change-history --append --flag NAME --old OLD --new NEW --operator USER --approval REF --rollback PLAN
  python3 ops_check.py packaged-entrypoints
  python3 ops_check.py model-promotion-evidence [--write] [--execute-replay]
  python3 ops_check.py resource-readiness
  python3 ops_check.py advanced-alpha-readiness
  python3 ops_check.py advanced-alpha-comparison
  python3 ops_check.py friction-heatmap
  python3 ops_check.py volume-clock-vpin YYYY-MM-DD --symbol AAPL
  python3 ops_check.py volatile-session-intelligence YYYY-MM-DD --symbols QQQ,AAPL,NVDA
  python3 ops_check.py cross-asset-lead-map
  python3 ops_check.py transformer-authority [--symbol AAPL]
  python3 ops_check.py trading-education-health
  python3 ops_check.py trading-education-ingest [--max-pages N] [--dry-run]
  python3 ops_check.py trading-education-review
  python3 ops_check.py trading-education-coverage
  python3 ops_check.py market-data-parity AAPL
  python3 ops_check.py market-data-parity AAPL --bars --date YYYY-MM-DD
  python3 ops_check.py research-export YYYY-MM-DD
  python3 ops_check.py lifecycle-analysis
  python3 ops_check.py decision-lifecycle-dashboard
  python3 ops_check.py decision-quality-review
  python3 ops_check.py exit-snapshot-backfill YYYY-MM-DD [--dry-run]
  python3 ops_check.py candidate-universe
  python3 ops_check.py candidate-outcome-backfill YYYY-MM-DD [--dry-run]
  python3 ops_check.py missed-buy-review YYYY-MM-DD
  python3 ops_check.py calibration-buckets
  python3 ops_check.py feature-attribution
  python3 ops_check.py post-trade-learning
  python3 ops_check.py symbol-patterns
  python3 ops_check.py pattern-learning-inputs
  python3 ops_check.py bar-pattern-backfill YYYY-MM-DD --symbol AAPL [--dry-run]
  python3 ops_check.py historical-bar-archive START_DATE --end-date YYYY-MM-DD --symbol AAPL
  python3 ops_check.py historical-bar-coverage [START_DATE] [--end-date YYYY-MM-DD]
  python3 ops_check.py historical-bar-progress [START_DATE] [--end-date YYYY-MM-DD]
  python3 ops_check.py historical-bar-readiness [START_DATE] [--end-date YYYY-MM-DD] [--include-db-quality]
  python3 ops_check.py historical-bar-retry-plan START_DATE [--end-date YYYY-MM-DD] [--execute]
  python3 ops_check.py historical-bar-models
  python3 ops_check.py historical-bar-paper-strategy SYMBOL [--action buy|sell]
  python3 ops_check.py historical-bar-paper-validation START_DATE [--end-date YYYY-MM-DD]
  python3 ops_check.py historical-bar-walk-forward START_DATE [--end-date YYYY-MM-DD]
  python3 ops_check.py historical-bar-validation START_DATE [--end-date YYYY-MM-DD]
  python3 ops_check.py ml-dataset-export START_DATE [END_DATE] [--output PATH] [--format jsonl|csv] [--max-rows N]
  python3 ops_check.py monday-readiness
  python3 ops_check.py exit-intelligence START_DATE [END_DATE]
  python3 ops_check.py sqlite-ownership
  python3 ops_check.py operator-intelligence [YYYY-MM-DD]
  python3 ops_check.py learning-readiness START_DATE [END_DATE]
  python3 ops_check.py learning-effectiveness START_DATE [END_DATE]
  python3 ops_check.py learning-artifacts YYYY-MM-DD
  python3 ops_check.py active-learning START_DATE [END_DATE]
  python3 ops_check.py rollout-contract
  python3 ops_check.py advisory-authority-report
  python3 ops_check.py paper-learning-authority
  python3 ops_check.py cross-layer-verification
  python3 ops_check.py ai-intelligence-review
  python3 ops_check.py migration-status
  python3 ops_check.py strong-days
  python3 ops_check.py strong-days 2026-05-26
  python3 ops_check.py conviction-persistence-health 2026-05-29
  python3 ops_check.py regime
  python3 ops_check.py regime-json
  python3 ops_check.py regime-matrix
  python3 ops_check.py all
  python3 ops_check.py filters 2026-05-08
  python3 ops_check.py jobs
  python3 ops_check.py job fill_poller
"""

import importlib
import os
import subprocess
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if SCRIPTS_DIR.exists():
    scripts_path = str(SCRIPTS_DIR)
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)

from trading_bot.ops_checks.bundles import run_all_bundle, run_premarket_bundle
from trading_bot.ops_checks.registry import OPS_COMMAND_SPECS, build_command_args
from trading_bot.ops_checks.subprocess_commands import (
    build_legacy_subprocess_commands,
    script_path,
)


@lru_cache(maxsize=None)
def _load_handler(handler_ref: str):
    module_name, function_name = handler_ref.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def _lazy_handler(handler_ref: str):
    function_name = handler_ref.rsplit(":", 1)[1]

    def _handler(*args, **kwargs):
        return _load_handler(handler_ref)(*args, **kwargs)

    _handler.__name__ = function_name
    _handler.__qualname__ = function_name
    return _handler


_LAZY_HANDLER_REFS = {
    "run_trading_education_ingest_cli": "pipeline.trading_education_ingest:main",
    "get_report_commands": "reports.registry:get_report_commands",
    "run_report": "reports.registry:run_report",
    "run_active_learning_integration": "services.ops_checks.active_learning_checks:run_active_learning_integration",
    "run_advanced_alpha_model_comparison": "services.ops_checks.advanced_alpha_model_comparison_checks:run_advanced_alpha_model_comparison",
    "run_advanced_alpha_readiness": "services.ops_checks.advanced_alpha_readiness_checks:run_advanced_alpha_readiness",
    "run_advisory_authority_report": "services.ops_checks.advisory_authority_checks:run_advisory_authority_report",
    "run_ai_intelligence_review": "services.ops_checks.ai_intelligence_review_checks:run_ai_intelligence_review",
    "run_architecture_surface_report": "services.ops_checks.architecture_surface_checks:run_architecture_surface_report",
    "run_auto_buy_health": "services.ops_checks.auto_buy_checks:run_auto_buy_health",
    "run_bar_pattern_backfill": "services.ops_checks.bar_pattern_checks:run_bar_pattern_backfill",
    "run_calibration_buckets": "services.ops_checks.calibration_bucket_checks:run_calibration_buckets",
    "run_candidate_outcome_backfill": "services.ops_checks.candidate_outcome_backfill_checks:run_candidate_outcome_backfill",
    "run_candidate_universe_report": "services.ops_checks.candidate_universe_checks:run_candidate_universe_report",
    "run_config_audit_report": "services.ops_checks.config_audit_checks:run_config_audit_report",
    "run_context_freshness": "services.ops_checks.context_freshness_checks:run_context_freshness",
    "run_data_freshness_gate": "services.ops_checks.context_freshness_checks:run_data_freshness_gate",
    "run_buy_opportunity_report": "services.ops_checks.conviction_checks:run_buy_opportunity_report",
    "run_claude_context_audit": "services.ops_checks.conviction_checks:run_claude_context_audit",
    "run_conviction_persistence_health": "services.ops_checks.conviction_checks:run_conviction_persistence_health",
    "run_conviction_stack_report": "services.ops_checks.conviction_checks:run_conviction_stack_report",
    "run_cross_asset_lead_lag_map_report": "services.ops_checks.cross_asset_lead_lag_checks:run_cross_asset_lead_lag_map_report",
    "run_cross_layer_verification_report": "services.ops_checks.cross_layer_verification_checks:run_cross_layer_verification_report",
    "run_database_backup_report": "services.ops_checks.database_backup_checks:run_database_backup_report",
    "run_dataset_health": "services.ops_checks.dataset_checks:run_dataset_health",
    "run_decision_quality_review": "services.ops_checks.decision_quality_checks:run_decision_quality_review",
    "run_event_context_validation": "services.ops_checks.event_context_validation_checks:run_event_context_validation",
    "run_event_source_coverage": "services.ops_checks.event_source_checks:run_event_source_coverage",
    "run_peak_bucket_report": "services.ops_checks.excursion_checks:run_peak_bucket_report",
    "run_winner_became_loser": "services.ops_checks.excursion_checks:run_winner_became_loser",
    "run_exit_intelligence_summary": "services.ops_checks.exit_intelligence_checks:run_exit_intelligence_summary",
    "run_exit_snapshot_backfill": "services.ops_checks.exit_snapshot_backfill_checks:run_exit_snapshot_backfill",
    "run_external_observability_readiness_report": "services.ops_checks.external_observability_readiness_checks:run_external_observability_readiness_report",
    "run_external_symbol_candidates": "services.ops_checks.external_symbol_candidate_checks:run_external_symbol_candidates",
    "run_external_symbol_discovery": "services.ops_checks.external_symbol_discovery_checks:run_external_symbol_discovery",
    "run_feature_attribution_report": "services.ops_checks.feature_attribution_checks:run_feature_attribution_report",
    "run_feature_health": "services.ops_checks.feature_checks:run_feature_health",
    "run_feature_watch": "services.ops_checks.feature_checks:run_feature_watch",
    "run_feature_flag_change_history_report": "services.ops_checks.feature_flag_change_history_checks:run_feature_flag_change_history_report",
    "run_feature_flag_inventory_report": "services.ops_checks.feature_flag_inventory_checks:run_feature_flag_inventory_report",
    "run_friction_heatmap": "services.ops_checks.friction_heatmap_checks:run_friction_heatmap",
    "run_full_session_paper_replay_report": "services.ops_checks.full_session_paper_replay_checks:run_full_session_paper_replay_report",
    "run_historical_bar_archive": "services.ops_checks.historical_bar_archive_checks:run_historical_bar_archive",
    "run_historical_bar_coverage": "services.ops_checks.historical_bar_coverage_checks:run_historical_bar_coverage",
    "run_historical_bar_model_readiness": "services.ops_checks.historical_bar_model_checks:run_historical_bar_model_readiness",
    "run_historical_bar_paper_strategy_report": "services.ops_checks.historical_bar_paper_strategy_checks:run_historical_bar_paper_strategy_report",
    "run_historical_bar_paper_validation": "services.ops_checks.historical_bar_paper_validation_checks:run_historical_bar_paper_validation",
    "run_historical_bar_walk_forward": "services.ops_checks.historical_bar_paper_validation_checks:run_historical_bar_walk_forward",
    "run_historical_bar_progress": "services.ops_checks.historical_bar_progress_checks:run_historical_bar_progress",
    "run_historical_bar_readiness": "services.ops_checks.historical_bar_readiness_checks:run_historical_bar_readiness",
    "run_historical_bar_validation": "services.ops_checks.historical_bar_validation_checks:run_historical_bar_validation",
    "run_incident_escalation_readiness_report": "services.ops_checks.incident_escalation_readiness_checks:run_incident_escalation_readiness_report",
    "run_incident_workflow_report": "services.ops_checks.incident_workflow_checks:run_incident_workflow_report",
    "run_intelligence_summary": "services.ops_checks.intelligence_checks:run_intelligence_summary",
    "run_learning_artifact_consumption": "services.ops_checks.learning_artifact_checks:run_learning_artifact_consumption",
    "run_learning_effectiveness": "services.ops_checks.learning_readiness_checks:run_learning_effectiveness",
    "run_learning_readiness": "services.ops_checks.learning_readiness_checks:run_learning_readiness",
    "run_lifecycle_analysis": "services.ops_checks.lifecycle_checks:run_lifecycle_analysis",
    "run_lifecycle_dashboard": "services.ops_checks.lifecycle_dashboard_checks:run_lifecycle_dashboard",
    "run_live_bar_pattern_capture_report": "services.ops_checks.live_bar_pattern_capture_checks:run_live_bar_pattern_capture_report",
    "run_local_load_probe_report": "services.ops_checks.local_load_probe_checks:run_local_load_probe_report",
    "run_log_ledger_consistency": "services.ops_checks.log_ledger_checks:run_log_ledger_consistency",
    "run_market_data_parity": "services.ops_checks.market_data_parity_checks:run_market_data_parity",
    "run_missed_buy_review": "services.ops_checks.missed_buy_review_checks:run_missed_buy_review",
    "run_ml_dataset_export_check": "services.ops_checks.ml_dataset_checks:run_ml_dataset_export_check",
    "run_model_promotion_evidence_report": "services.ops_checks.model_promotion_evidence_checks:run_model_promotion_evidence_report",
    "run_model_validation_governance_report": "services.ops_checks.model_validation_governance_checks:run_model_validation_governance_report",
    "run_monday_readiness_check": "services.ops_checks.monday_readiness_checks:run_monday_readiness_check",
    "run_observability_health": "services.ops_checks.observability_health_checks:run_observability_health",
    "run_operator_intelligence_dashboard": "services.ops_checks.operator_intelligence_dashboard_checks:run_operator_intelligence_dashboard",
    "run_order_health": "services.ops_checks.order_checks:run_order_health",
    "run_packaged_entrypoint_validation_report": "services.ops_checks.packaged_entrypoint_validation_checks:run_packaged_entrypoint_validation_report",
    "run_paper_learning_authority_report": "services.ops_checks.paper_learning_authority_checks:run_paper_learning_authority_report",
    "run_paper_replay_load_probe_report": "services.ops_checks.paper_replay_load_probe_checks:run_paper_replay_load_probe_report",
    "run_pattern_learning_inputs_report": "services.ops_checks.pattern_learning_inputs_checks:run_pattern_learning_inputs_report",
    "run_point_in_time_archive": "services.ops_checks.point_in_time_archive_checks:run_point_in_time_archive",
    "run_portfolio_risk_report": "services.ops_checks.portfolio_risk_checks:run_portfolio_risk_report",
    "run_post_trade_learning_report": "services.ops_checks.post_trade_learning_checks:run_post_trade_learning_report",
    "run_rejected_outcomes_health": "services.ops_checks.rejected_outcome_checks:run_rejected_outcomes_health",
    "run_rejection_summary": "services.ops_checks.rejection_checks:run_rejection_summary",
    "run_research_export": "services.ops_checks.research_export_checks:run_research_export",
    "run_resource_readiness": "services.ops_checks.resource_readiness_checks:run_resource_readiness",
    "run_rollout_contract_report": "services.ops_checks.rollout_contract_checks:run_rollout_contract_report",
    "run_runtime_health": "services.ops_checks.runtime_checks:run_runtime_health",
    "run_runtime_health_trend": "services.ops_checks.runtime_checks:run_runtime_health_trend",
    "run_secrets_hygiene_report": "services.ops_checks.secrets_hygiene_checks:run_secrets_hygiene_report",
    "run_secrets_manager_readiness_report": "services.ops_checks.secrets_manager_readiness_checks:run_secrets_manager_readiness_report",
    "run_setup_breakdown": "services.ops_checks.setup_breakdown:run_setup_breakdown",
    "run_shadow_prediction_report": "services.ops_checks.shadow_prediction_checks:run_shadow_prediction_report",
    "run_signal_source_readiness": "services.ops_checks.signal_source_checks:run_signal_source_readiness",
    "run_decision_snapshot_health": "services.ops_checks.snapshot_checks:run_decision_snapshot_health",
    "run_sqlite_ownership_report": "services.ops_checks.sqlite_ownership_checks:run_sqlite_ownership_report",
    "run_symbol_pattern_outcomes": "services.ops_checks.symbol_pattern_checks:run_symbol_pattern_outcomes",
    "run_trading_education_coverage": "services.ops_checks.trading_education_checks:run_trading_education_coverage",
    "run_trading_education_health": "services.ops_checks.trading_education_checks:run_trading_education_health",
    "run_trading_education_review": "services.ops_checks.trading_education_checks:run_trading_education_review",
    "run_transformer_authority_report": "services.ops_checks.transformer_authority_checks:run_transformer_authority_report",
    "run_volatile_session_intelligence_report": "services.ops_checks.volatile_session_intelligence_checks:run_volatile_session_intelligence_report",
    "run_volume_clock_vpin_report": "services.ops_checks.volume_clock_vpin_checks:run_volume_clock_vpin_report",
}

run_trading_education_ingest_cli = _lazy_handler(
    _LAZY_HANDLER_REFS["run_trading_education_ingest_cli"]
)
get_report_commands = _lazy_handler(_LAZY_HANDLER_REFS["get_report_commands"])
run_report = _lazy_handler(_LAZY_HANDLER_REFS["run_report"])
run_active_learning_integration = _lazy_handler(
    _LAZY_HANDLER_REFS["run_active_learning_integration"]
)
run_advanced_alpha_model_comparison = _lazy_handler(
    _LAZY_HANDLER_REFS["run_advanced_alpha_model_comparison"]
)
run_advanced_alpha_readiness = _lazy_handler(_LAZY_HANDLER_REFS["run_advanced_alpha_readiness"])
run_advisory_authority_report = _lazy_handler(_LAZY_HANDLER_REFS["run_advisory_authority_report"])
run_ai_intelligence_review = _lazy_handler(_LAZY_HANDLER_REFS["run_ai_intelligence_review"])
run_architecture_surface_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_architecture_surface_report"]
)
run_auto_buy_health = _lazy_handler(_LAZY_HANDLER_REFS["run_auto_buy_health"])
run_bar_pattern_backfill = _lazy_handler(_LAZY_HANDLER_REFS["run_bar_pattern_backfill"])
run_calibration_buckets = _lazy_handler(_LAZY_HANDLER_REFS["run_calibration_buckets"])
run_candidate_outcome_backfill = _lazy_handler(_LAZY_HANDLER_REFS["run_candidate_outcome_backfill"])
run_candidate_universe_report = _lazy_handler(_LAZY_HANDLER_REFS["run_candidate_universe_report"])
run_config_audit_report = _lazy_handler(_LAZY_HANDLER_REFS["run_config_audit_report"])
run_context_freshness = _lazy_handler(_LAZY_HANDLER_REFS["run_context_freshness"])
run_data_freshness_gate = _lazy_handler(_LAZY_HANDLER_REFS["run_data_freshness_gate"])
run_buy_opportunity_report = _lazy_handler(_LAZY_HANDLER_REFS["run_buy_opportunity_report"])
run_claude_context_audit = _lazy_handler(_LAZY_HANDLER_REFS["run_claude_context_audit"])
run_conviction_persistence_health = _lazy_handler(
    _LAZY_HANDLER_REFS["run_conviction_persistence_health"]
)
run_conviction_stack_report = _lazy_handler(_LAZY_HANDLER_REFS["run_conviction_stack_report"])
run_cross_asset_lead_lag_map_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_cross_asset_lead_lag_map_report"]
)
run_cross_layer_verification_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_cross_layer_verification_report"]
)
run_database_backup_report = _lazy_handler(_LAZY_HANDLER_REFS["run_database_backup_report"])
run_dataset_health = _lazy_handler(_LAZY_HANDLER_REFS["run_dataset_health"])
run_decision_quality_review = _lazy_handler(_LAZY_HANDLER_REFS["run_decision_quality_review"])
run_event_context_validation = _lazy_handler(_LAZY_HANDLER_REFS["run_event_context_validation"])
run_event_source_coverage = _lazy_handler(_LAZY_HANDLER_REFS["run_event_source_coverage"])
run_peak_bucket_report = _lazy_handler(_LAZY_HANDLER_REFS["run_peak_bucket_report"])
run_winner_became_loser = _lazy_handler(_LAZY_HANDLER_REFS["run_winner_became_loser"])
run_exit_intelligence_summary = _lazy_handler(_LAZY_HANDLER_REFS["run_exit_intelligence_summary"])
run_exit_snapshot_backfill = _lazy_handler(_LAZY_HANDLER_REFS["run_exit_snapshot_backfill"])
run_external_observability_readiness_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_external_observability_readiness_report"]
)
run_external_symbol_candidates = _lazy_handler(_LAZY_HANDLER_REFS["run_external_symbol_candidates"])
run_external_symbol_discovery = _lazy_handler(_LAZY_HANDLER_REFS["run_external_symbol_discovery"])
run_feature_attribution_report = _lazy_handler(_LAZY_HANDLER_REFS["run_feature_attribution_report"])
run_feature_health = _lazy_handler(_LAZY_HANDLER_REFS["run_feature_health"])
run_feature_watch = _lazy_handler(_LAZY_HANDLER_REFS["run_feature_watch"])
run_feature_flag_change_history_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_feature_flag_change_history_report"]
)
run_feature_flag_inventory_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_feature_flag_inventory_report"]
)
run_friction_heatmap = _lazy_handler(_LAZY_HANDLER_REFS["run_friction_heatmap"])
run_full_session_paper_replay_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_full_session_paper_replay_report"]
)
run_historical_bar_archive = _lazy_handler(_LAZY_HANDLER_REFS["run_historical_bar_archive"])
run_historical_bar_coverage = _lazy_handler(_LAZY_HANDLER_REFS["run_historical_bar_coverage"])
run_historical_bar_model_readiness = _lazy_handler(
    _LAZY_HANDLER_REFS["run_historical_bar_model_readiness"]
)
run_historical_bar_paper_strategy_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_historical_bar_paper_strategy_report"]
)
run_historical_bar_paper_validation = _lazy_handler(
    _LAZY_HANDLER_REFS["run_historical_bar_paper_validation"]
)
run_historical_bar_walk_forward = _lazy_handler(
    _LAZY_HANDLER_REFS["run_historical_bar_walk_forward"]
)
run_historical_bar_progress = _lazy_handler(_LAZY_HANDLER_REFS["run_historical_bar_progress"])
run_historical_bar_readiness = _lazy_handler(_LAZY_HANDLER_REFS["run_historical_bar_readiness"])
run_historical_bar_validation = _lazy_handler(_LAZY_HANDLER_REFS["run_historical_bar_validation"])
run_incident_escalation_readiness_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_incident_escalation_readiness_report"]
)
run_incident_workflow_report = _lazy_handler(_LAZY_HANDLER_REFS["run_incident_workflow_report"])
run_intelligence_summary = _lazy_handler(_LAZY_HANDLER_REFS["run_intelligence_summary"])
run_learning_artifact_consumption = _lazy_handler(
    _LAZY_HANDLER_REFS["run_learning_artifact_consumption"]
)
run_learning_effectiveness = _lazy_handler(_LAZY_HANDLER_REFS["run_learning_effectiveness"])
run_learning_readiness = _lazy_handler(_LAZY_HANDLER_REFS["run_learning_readiness"])
run_lifecycle_analysis = _lazy_handler(_LAZY_HANDLER_REFS["run_lifecycle_analysis"])
run_lifecycle_dashboard = _lazy_handler(_LAZY_HANDLER_REFS["run_lifecycle_dashboard"])
run_live_bar_pattern_capture_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_live_bar_pattern_capture_report"]
)
run_local_load_probe_report = _lazy_handler(_LAZY_HANDLER_REFS["run_local_load_probe_report"])
run_log_ledger_consistency = _lazy_handler(_LAZY_HANDLER_REFS["run_log_ledger_consistency"])
run_market_data_parity = _lazy_handler(_LAZY_HANDLER_REFS["run_market_data_parity"])
run_missed_buy_review = _lazy_handler(_LAZY_HANDLER_REFS["run_missed_buy_review"])
run_ml_dataset_export_check = _lazy_handler(_LAZY_HANDLER_REFS["run_ml_dataset_export_check"])
run_model_promotion_evidence_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_model_promotion_evidence_report"]
)
run_model_validation_governance_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_model_validation_governance_report"]
)
run_monday_readiness_check = _lazy_handler(_LAZY_HANDLER_REFS["run_monday_readiness_check"])
run_observability_health = _lazy_handler(_LAZY_HANDLER_REFS["run_observability_health"])
run_operator_intelligence_dashboard = _lazy_handler(
    _LAZY_HANDLER_REFS["run_operator_intelligence_dashboard"]
)
run_order_health = _lazy_handler(_LAZY_HANDLER_REFS["run_order_health"])
run_packaged_entrypoint_validation_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_packaged_entrypoint_validation_report"]
)
run_paper_learning_authority_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_paper_learning_authority_report"]
)
run_paper_replay_load_probe_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_paper_replay_load_probe_report"]
)
run_pattern_learning_inputs_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_pattern_learning_inputs_report"]
)
run_point_in_time_archive = _lazy_handler(_LAZY_HANDLER_REFS["run_point_in_time_archive"])
run_portfolio_risk_report = _lazy_handler(_LAZY_HANDLER_REFS["run_portfolio_risk_report"])
run_post_trade_learning_report = _lazy_handler(_LAZY_HANDLER_REFS["run_post_trade_learning_report"])
run_rejected_outcomes_health = _lazy_handler(_LAZY_HANDLER_REFS["run_rejected_outcomes_health"])
run_rejection_summary = _lazy_handler(_LAZY_HANDLER_REFS["run_rejection_summary"])
run_research_export = _lazy_handler(_LAZY_HANDLER_REFS["run_research_export"])
run_resource_readiness = _lazy_handler(_LAZY_HANDLER_REFS["run_resource_readiness"])
run_rollout_contract_report = _lazy_handler(_LAZY_HANDLER_REFS["run_rollout_contract_report"])
run_runtime_health = _lazy_handler(_LAZY_HANDLER_REFS["run_runtime_health"])
run_runtime_health_trend = _lazy_handler(_LAZY_HANDLER_REFS["run_runtime_health_trend"])
run_secrets_hygiene_report = _lazy_handler(_LAZY_HANDLER_REFS["run_secrets_hygiene_report"])
run_secrets_manager_readiness_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_secrets_manager_readiness_report"]
)
run_setup_breakdown = _lazy_handler(_LAZY_HANDLER_REFS["run_setup_breakdown"])
run_shadow_prediction_report = _lazy_handler(_LAZY_HANDLER_REFS["run_shadow_prediction_report"])
run_signal_source_readiness = _lazy_handler(_LAZY_HANDLER_REFS["run_signal_source_readiness"])
run_decision_snapshot_health = _lazy_handler(_LAZY_HANDLER_REFS["run_decision_snapshot_health"])
run_sqlite_ownership_report = _lazy_handler(_LAZY_HANDLER_REFS["run_sqlite_ownership_report"])
run_symbol_pattern_outcomes = _lazy_handler(_LAZY_HANDLER_REFS["run_symbol_pattern_outcomes"])
run_trading_education_coverage = _lazy_handler(_LAZY_HANDLER_REFS["run_trading_education_coverage"])
run_trading_education_health = _lazy_handler(_LAZY_HANDLER_REFS["run_trading_education_health"])
run_trading_education_review = _lazy_handler(_LAZY_HANDLER_REFS["run_trading_education_review"])
run_transformer_authority_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_transformer_authority_report"]
)
run_volatile_session_intelligence_report = _lazy_handler(
    _LAZY_HANDLER_REFS["run_volatile_session_intelligence_report"]
)
run_volume_clock_vpin_report = _lazy_handler(_LAZY_HANDLER_REFS["run_volume_clock_vpin_report"])

BASE_DIR = ROOT_DIR
SCRIPT_DIR = BASE_DIR / "scripts"
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")


def reexec_under_venv_if_available():
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])


reexec_under_venv_if_available()


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


def _script(name: str) -> str:
    return script_path(SCRIPT_DIR, name)


def _compat_env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath_parts = [str(SCRIPT_DIR), str(BASE_DIR)]
    if env.get("PYTHONPATH"):
        pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    return env


# Non-report operational scripts still dispatched via subprocess.
# *_report.py scripts are handled in-process via the reports/ package instead.
COMMANDS = build_legacy_subprocess_commands(SCRIPT_DIR)


class _LazyReportCommands:
    def _commands(self):
        return get_report_commands()

    def __contains__(self, command: str) -> bool:
        return command in self._commands()

    def __getitem__(self, command: str):
        return self._commands()[command]

    def get(self, command: str, default=None):
        return self._commands().get(command, default)

    def keys(self):
        return self._commands().keys()

    def items(self):
        return self._commands().items()

    def values(self):
        return self._commands().values()


REPORT_COMMANDS = _LazyReportCommands()


def _print_section(label: str) -> None:
    print()
    print("=" * 72)
    print(f"  {label}")
    print("=" * 72)


def run(label, args):
    _print_section(label)

    try:
        r = subprocess.run(
            [sys.executable] + args,
            cwd=BASE_DIR,
            env=_compat_env(),
            text=True,
            timeout=180,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"[FAIL] {label} failed: {e}")
        return False


def check_market_context_file():
    import json

    path = BASE_DIR / "market_context.json"

    print()
    print("=" * 72)
    print("  Market Context Check")
    print("=" * 72)

    if not path.exists():
        print(f"[FAIL] missing {path}")
        return False

    try:
        data = json.loads(path.read_text())
    except Exception as e:
        print(f"[FAIL] could not parse {path}: {e}")
        return False

    required_top = {
        "market_date",
        "macro_sentiment",
        "macro_summary",
        "symbols",
    }

    required_symbol = {
        "bias",
        "reason",
        "confidence",
        "fundamental_score",
        "risk_level",
        "entry_quality",
        "avoid_type",
    }

    ok = True

    missing_top = sorted(required_top - set(data.keys()))
    if missing_top:
        print(f"[FAIL] missing top-level fields: {missing_top}")
        ok = False

    market_date = data.get("market_date")
    source = data.get("source")
    fmt = data.get("format")
    symbols = data.get("symbols") or {}

    print(f"market_date : {market_date}")
    print(f"source      : {source}")
    print(f"format      : {fmt}")
    print(f"symbols     : {len(symbols)}")
    print(f"macro       : {data.get('macro_sentiment')}")
    print(f"regime      : {data.get('macro_regime')}")
    print(f"risk_mult   : {data.get('risk_multiplier')}")
    print(f"max_pos     : {data.get('max_new_positions')}")
    print(f"block_buys  : {data.get('block_new_buys')}")

    # Intraday refresh staleness check — only meaningful during market hours.
    from datetime import datetime, timedelta, timezone

    intraday_refresh_at = data.get("intraday_refresh_at")
    print(f"intraday_refresh_at : {intraday_refresh_at or 'not present'}")
    now_utc = datetime.now(timezone.utc)
    et_offset = timedelta(hours=-4)  # EDT; close enough for a staleness gate
    now_et = now_utc + et_offset
    market_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    is_market_hours = now_et.weekday() < 5 and market_open_et <= now_et <= market_close_et
    INTRADAY_REFRESH_STALE_MINUTES = 90
    if is_market_hours:
        if not intraday_refresh_at:
            print(
                "[WARN] intraday_refresh_at absent during market hours — intraday_context_refresh.py may not have run yet"
            )
        else:
            try:
                refresh_dt = datetime.fromisoformat(intraday_refresh_at).astimezone(timezone.utc)
                age_minutes = (now_utc - refresh_dt).total_seconds() / 60
                if age_minutes > INTRADAY_REFRESH_STALE_MINUTES:
                    print(
                        f"[WARN] intraday_refresh_at is {age_minutes:.0f} min old (>{INTRADAY_REFRESH_STALE_MINUTES} min) — refresh may be silently failing"
                    )
                    ok = False
                else:
                    print(
                        f"[OK] intraday_refresh_at is {age_minutes:.0f} min old (within {INTRADAY_REFRESH_STALE_MINUTES} min)"
                    )
            except Exception as e:
                print(f"[WARN] could not parse intraday_refresh_at '{intraday_refresh_at}': {e}")
    else:
        if intraday_refresh_at:
            print("[OK] intraday_refresh_at present (staleness check skipped outside market hours)")

    if not isinstance(symbols, dict) or not symbols:
        print("[FAIL] symbols is empty or not an object")
        return False

    bad_symbols = []
    avoid_type_errors = []
    bias_counts = {}

    for sym, entry in symbols.items():
        entry = entry or {}
        bias = entry.get("bias", "missing")
        bias_counts[bias] = bias_counts.get(bias, 0) + 1

        missing = sorted(required_symbol - set(entry.keys()))
        if missing:
            bad_symbols.append((sym, missing))

        avoid_type = entry.get("avoid_type")
        if bias != "avoid" and avoid_type is not None:
            avoid_type_errors.append((sym, bias, avoid_type))

    print(f"bias_counts : {bias_counts}")

    if bad_symbols:
        print("[FAIL] symbols missing required fields:")
        for sym, missing in bad_symbols[:25]:
            print(f"  {sym}: {missing}")
        ok = False
    else:
        print("[OK] required per-symbol fields present")

    if avoid_type_errors:
        print("[FAIL] avoid_type set on non-avoid symbols:")
        for sym, bias, avoid_type in avoid_type_errors[:25]:
            print(f"  {sym}: bias={bias} avoid_type={avoid_type}")
        ok = False
    else:
        print("[OK] avoid_type only set for avoid symbols")

    if source != "market_brief_builder":
        print(f"[WARN] source is not market_brief_builder: {source}")

    if fmt != "rich_market_brief_v1":
        print(f"[WARN] format is not rich_market_brief_v1: {fmt}")

    if ok:
        print("[OK] market_context.json schema check passed")
    else:
        print("[FAIL] market_context.json schema check failed")

    return ok


def intelligence_summary(target_date):
    return run_intelligence_summary(target_date, base_dir=BASE_DIR)


def _table_exists(con, table_name):
    row = con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _count_table(con, table_name, where_sql="", params=()):
    if not _table_exists(con, table_name):
        return None

    sql = f"SELECT COUNT(*) AS n FROM {table_name}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    return con.execute(sql, params).fetchone()["n"]


def dataset_health(target_date):
    return run_dataset_health(target_date, base_dir=BASE_DIR)


def feature_health(target_date):
    return run_feature_health(target_date, base_dir=BASE_DIR)


def feature_watch(target_date):
    return run_feature_watch(target_date, base_dir=BASE_DIR)


def live_bar_pattern_capture(target_date):
    return run_live_bar_pattern_capture_report(
        target_date,
        base_dir=BASE_DIR,
        max_age_minutes=_int_option("--max-age-minutes", 5),
        min_symbols=_int_option("--min-symbols", 1),
        timeframe=_str_option("--timeframe", "1m"),
        limit=_int_option("--limit", 12),
    )


def rejection_summary(target_date):
    return run_rejection_summary(target_date, base_dir=BASE_DIR)


def migration_status_check():
    from db_migrations import status as migration_status

    print()
    print("=" * 72)
    print("  DB Migration Status")
    print("=" * 72)

    try:
        rows = migration_status(BASE_DIR / "trades.db")
    except Exception as e:
        print(f"[FAIL] migration status check failed: {e}")
        return False

    pending = [row for row in rows if not row["applied"]]
    for row in rows:
        marker = "applied" if row["applied"] else "pending"
        print(f"{marker:>8}  {row['migration_id']}  {row['description']}")

    if pending:
        print(f"[FAIL] {len(pending)} pending DB migration(s)")
        return False

    print("[OK] all DB migrations applied")
    return True


def rejected_outcomes_health(target_date):
    return run_rejected_outcomes_health(
        target_date,
        base_dir=BASE_DIR,
        env_get=os.getenv,
    )


def auto_buy_health(target_date):
    return run_auto_buy_health(target_date, base_dir=BASE_DIR)


def signal_source_readiness(target_date):
    return run_signal_source_readiness(target_date, base_dir=BASE_DIR)


def decision_snapshot_health(target_date):
    return run_decision_snapshot_health(target_date, base_dir=BASE_DIR)


def policy_artifact_health():
    from datetime import datetime, timezone

    from policy_artifacts import policy_artifact_status

    print()
    print("=" * 72)
    print("  Policy Artifact Health")
    print("=" * 72)

    status = policy_artifact_status(BASE_DIR)
    print(f"enabled     : {status.get('enabled')}")
    print(f"effect      : {status.get('runtime_effect')}")
    print(f"state_hash  : {status.get('state_hash')}")
    registry = status.get("registry") or {}
    known_good = registry.get("known_good") or {}
    print(
        f"registry    : entries={registry.get('entry_count', 0)} path={registry.get('registry_path')}"
    )
    print(f"known_good  : {known_good.get('artifact_set_id') or '-'}")

    ok = True
    now = datetime.now(timezone.utc)
    for name, item in status.get("files", {}).items():
        exists = item.get("exists")
        mtime = item.get("mtime")
        age_hours = None
        if mtime:
            try:
                age_hours = (now - datetime.fromisoformat(mtime)).total_seconds() / 3600
            except Exception:
                age_hours = None
        age_s = f"{age_hours:.1f}h" if age_hours is not None else "-"
        print(
            f"  {name:<36} exists={str(exists):<5} age={age_s:>8} "
            f"generated_at={item.get('generated_at') or '-'} sha={str(item.get('sha256') or '-')[:12]}"
        )
        if name == "policy_backtest_summary.json":
            rec = item.get("recommendation")
            if rec:
                print(
                    f"    policy_backtest_recommendation={rec} reason={item.get('reason') or '-'}"
                )
                if rec == "policy_too_loose":
                    print(
                        "    [WARN] decision policy remains too loose; keep under review and do not promote"
                    )
        if not exists:
            ok = False
            print(f"    [WARN] missing policy artifact: {name}")
        elif age_hours is not None and age_hours > 72:
            print(f"    [WARN] artifact older than 72h: {name}")

    if not registry.get("entry_count"):
        ok = False
        print("[WARN] no policy artifact registry entries found")
    if not known_good.get("artifact_set_id"):
        ok = False
        print("[WARN] no known-good policy artifact pointer found")

    print()
    print(
        "[OK] policy artifact check completed"
        if ok
        else "[WARN] policy artifact check found issues"
    )
    return ok


def retention_health():
    from ml_platform.retention import retention_policy

    print()
    print("=" * 72)
    print("  ML/Audit Retention Policy")
    print("=" * 72)

    policy = retention_policy()
    print(f"version       : {policy['version']}")
    print(f"destructive   : {policy['destructive_compaction_enabled']}")
    print(f"rule          : {policy['rule']}")
    print()
    for row in policy["rules"]:
        window = (
            row["default_window_days"] if row["default_window_days"] is not None else "preserve"
        )
        print(
            f"  {row['name']:<30} tier={row['tier']:<5} window={str(window):<8} storage={row['storage']}"
        )

    print()
    print("[OK] retention policy is classified; no destructive compaction is enabled")
    return True


def order_health(target_date):
    return run_order_health(target_date, base_dir=BASE_DIR)


def runtime_health(target_date):
    return run_runtime_health(target_date, base_dir=BASE_DIR)


def runtime_health_trend(start_date, end_date):
    return run_runtime_health_trend(start_date, end_date=end_date, base_dir=BASE_DIR)


def observability_health(target_date):
    return run_observability_health(target_date, base_dir=BASE_DIR)


def context_freshness(target_date):
    return run_context_freshness(target_date, base_dir=BASE_DIR)


def data_freshness_gate(target_date):
    return run_data_freshness_gate(target_date, base_dir=BASE_DIR)


def event_source_coverage(target_date):
    return run_event_source_coverage(target_date, base_dir=BASE_DIR)


def event_context_validation(target_date):
    return run_event_context_validation(target_date, base_dir=BASE_DIR)


def external_symbol_discovery(start_date):
    return run_external_symbol_discovery(
        start_date,
        base_dir=BASE_DIR,
        end_date=_str_option("--end-date", "") or None,
        min_mentions=_int_option("--min-mentions", 2),
        limit=_int_option("--limit", 12),
    )


def external_symbol_candidates() -> bool:
    return run_external_symbol_candidates(
        base_dir=BASE_DIR,
        state_path=_str_option("--state-path", "") or None,
        limit=_int_option("--limit", 20),
    )


def log_ledger_consistency():
    return run_log_ledger_consistency(base_dir=BASE_DIR)


def portfolio_risk(target_date):
    return run_portfolio_risk_report(target_date, base_dir=BASE_DIR)


def production_evidence(target_date):
    checks = [
        runtime_health(target_date),
        log_ledger_consistency(),
        context_freshness(target_date),
        event_source_coverage(target_date),
        event_context_validation(target_date),
        portfolio_risk(target_date),
        lifecycle_analysis(target_date),
        decision_lifecycle_dashboard(target_date),
        calibration_buckets(target_date),
        setup_breakdown(target_date),
        conviction_persistence_health(target_date),
        feature_attribution(target_date),
        post_trade_learning(target_date),
        paper_learning_authority(target_date),
        cross_layer_verification(target_date),
        ai_intelligence_review(target_date),
    ]
    print()
    print("=" * 72)
    if all(checks):
        print("[OK] production evidence checks completed successfully")
        return True
    print("[WARN] production evidence checks found gaps")
    return False


def resource_readiness():
    return run_resource_readiness(base_dir=BASE_DIR)


def local_load_probe():
    return run_local_load_probe_report(
        requests=_int_option("--requests", 100),
        concurrency=_int_option("--concurrency", 4),
        symbol=_str_option("--symbol", "AAPL"),
        action=_str_option("--action", "buy"),
    )


def paper_replay_load_probe():
    return run_paper_replay_load_probe_report(
        requests=_int_option("--requests", 100),
        concurrency=_int_option("--concurrency", 4),
        symbol=_str_option("--symbol", "AAPL"),
        action=_str_option("--action", "buy"),
    )


def full_session_paper_replay():
    symbols = tuple(
        symbol.strip().upper()
        for symbol in _str_option("--symbols", "AAPL").split(",")
        if symbol.strip()
    )
    return run_full_session_paper_replay_report(
        symbols=symbols,
        events_per_symbol_per_minute=_int_option("--events-per-minute", 1),
        session_minutes=_int_option("--session-minutes", 390),
        concurrency=_int_option("--concurrency", 4),
        execute="--execute" in sys.argv,
        max_execute_requests=_int_option("--max-requests", 1000),
    )


def external_observability_readiness():
    return run_external_observability_readiness_report()


def secrets_manager_readiness():
    return run_secrets_manager_readiness_report()


def incident_escalation_readiness():
    return run_incident_escalation_readiness_report(base_dir=BASE_DIR)


def feature_flag_change_history():
    return run_feature_flag_change_history_report(
        base_dir=BASE_DIR,
        append="--append" in sys.argv,
        flag=_str_option("--flag", ""),
        old_value=_str_option("--old", ""),
        new_value=_str_option("--new", ""),
        operator=_str_option("--operator", ""),
        approval_reference=_str_option("--approval", ""),
        rollback_plan=_str_option("--rollback", ""),
    )


def packaged_entrypoints():
    return run_packaged_entrypoint_validation_report(base_dir=BASE_DIR)


def model_promotion_evidence():
    symbols = tuple(
        symbol.strip().upper()
        for symbol in _str_option("--symbols", "AAPL").split(",")
        if symbol.strip()
    )
    return run_model_promotion_evidence_report(
        base_dir=BASE_DIR,
        write="--write" in sys.argv,
        operator=_str_option("--operator", "unassigned"),
        approval_reference=_str_option("--approval", ""),
        replay_symbols=symbols,
        execute_replay="--execute-replay" in sys.argv,
        max_replay_requests=_int_option("--max-requests", 1000),
    )


def incident_workflow():
    title = _str_option("--title", "")
    if not title and len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
        title = sys.argv[2]
    if not title:
        title = "untitled incident"
    return run_incident_workflow_report(
        base_dir=BASE_DIR,
        title=title,
        severity=_str_option("--severity", "medium"),
        create="--create" in sys.argv,
    )


def config_audit():
    return run_config_audit_report(base_dir=BASE_DIR)


def feature_flags():
    return run_feature_flag_inventory_report(
        base_dir=BASE_DIR,
        limit=_int_option("--limit", 40),
    )


def model_governance():
    return run_model_validation_governance_report(
        min_rows=_int_option("--min-rows", 5000),
        min_symbols=_int_option("--min-symbols", 20),
        min_accuracy=_float_option("--min-accuracy", 0.50),
        limit=_int_option("--limit", 12),
    )


def secrets_hygiene():
    env_file = Path(_str_option("--env-file", str(ENV_FILE)))
    return run_secrets_hygiene_report(base_dir=BASE_DIR, env_file=env_file)


def architecture_surface():
    return run_architecture_surface_report(base_dir=BASE_DIR)


def advanced_alpha_readiness(target_date):
    return run_advanced_alpha_readiness(target_date, base_dir=BASE_DIR)


def advanced_alpha_comparison(target_date):
    return run_advanced_alpha_model_comparison(target_date, base_dir=BASE_DIR)


def friction_heatmap(target_date):
    return run_friction_heatmap(target_date, base_dir=BASE_DIR)


def volume_clock_vpin(target_date):
    symbol = _str_option("--symbol", "")
    if not symbol and len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        symbol = sys.argv[3]
    if not symbol:
        print("[FAIL] --symbol is required")
        return False
    return run_volume_clock_vpin_report(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        bucket_volume=float(_str_option("--bucket-volume", "500000")),
        window_buckets=_int_option("--window-buckets", 20),
        timeframe=_str_option("--timeframe", "1m"),
        start_time=_str_option("--start-time", ""),
        end_time=_str_option("--end-time", ""),
        limit=_int_option("--max-rows", 20000),
        print_limit=_int_option("--limit", 12),
    )


def volatile_session_intelligence(target_date):
    raw_symbols = _str_option("--symbols", "QQQ,AAPL,NVDA,MSFT,AMD,TSLA")
    symbols = [item.strip().upper() for item in raw_symbols.split(",") if item.strip()]
    return run_volatile_session_intelligence_report(
        target_date,
        base_dir=BASE_DIR,
        symbols=symbols,
        bucket_volume=float(_str_option("--bucket-volume", "500000")),
        window_buckets=_int_option("--window-buckets", 20),
        start_time=_str_option("--start-time", "09:30"),
        end_time=_str_option("--end-time", "10:00"),
        timeframe=_str_option("--timeframe", "1m"),
    )


def cross_asset_lead_map():
    return run_cross_asset_lead_lag_map_report(
        limit=_int_option("--limit", 20),
    )


def transformer_authority():
    return run_transformer_authority_report(
        base_dir=BASE_DIR,
        symbol=_str_option("--symbol", "SPY"),
        action=_str_option("--action", "buy"),
    )


def trading_education_health():
    return run_trading_education_health(base_dir=BASE_DIR)


def trading_education_ingest():
    return run_trading_education_ingest_cli(sys.argv[2:]) == 0


def trading_education_review():
    return run_trading_education_review(base_dir=BASE_DIR)


def trading_education_coverage():
    return run_trading_education_coverage(base_dir=BASE_DIR)


def market_data_parity(symbol):
    mode = "bars" if "--bars" in sys.argv else "quote"
    target_date = None
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            target_date = sys.argv[idx + 1]
    return run_market_data_parity(symbol, base_dir=BASE_DIR, mode=mode, target_date=target_date)


def lifecycle_analysis(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_lifecycle_analysis(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        samples=_int_option("--samples", 15),
    )


def decision_lifecycle_dashboard(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_lifecycle_dashboard(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        samples=_int_option("--samples", 15),
    )


def decision_quality_review(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_decision_quality_review(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        samples=_int_option("--samples", 20),
    )


def exit_snapshot_backfill(target_date):
    end_date = None
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        end_date = sys.argv[3]
    return run_exit_snapshot_backfill(
        target_date,
        end_date=end_date,
        dry_run="--dry-run" in sys.argv,
        limit=_int_option("--limit", 0) or None,
    )


def candidate_universe(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_candidate_universe_report(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
    )


def candidate_outcome_backfill(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_candidate_outcome_backfill(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        limit=_int_option("--limit", 0) or None,
        dry_run="--dry-run" in sys.argv,
        overwrite="--overwrite" in sys.argv,
    )


def missed_buy_review(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_missed_buy_review(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        samples=_int_option("--samples", 20),
        min_mfe_pct=_float_option("--min-mfe-pct", 0.8),
    )


def calibration_buckets(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_calibration_buckets(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_sample_size=_int_option("--min-sample-size", 5),
        limit=_int_option("--limit", 20),
    )


def feature_attribution(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_feature_attribution_report(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_sample_size=_int_option("--min-sample-size", 30),
        rolling_window_size=_int_option("--rolling-window-size", 50),
    )


def post_trade_learning(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_post_trade_learning_report(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
    )


def symbol_patterns(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_symbol_pattern_outcomes(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_sample_size=_int_option("--min-sample-size", 30),
        limit=_int_option("--limit", 20),
    )


def pattern_learning_inputs(target_date):
    return run_pattern_learning_inputs_report(
        target_date,
        base_dir=BASE_DIR,
        limit=_int_option("--limit", 20),
    )


def _str_option(name: str, default: str = "") -> str:
    if name not in sys.argv:
        return default
    idx = sys.argv.index(name)
    if idx + 1 >= len(sys.argv):
        return default
    return sys.argv[idx + 1]


def bar_pattern_backfill(target_date: str) -> bool:
    symbol = _str_option("--symbol", "")
    if not symbol and len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        symbol = sys.argv[3]
    return run_bar_pattern_backfill(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        dry_run="--dry-run" in sys.argv,
        timeframe_minutes=_int_option("--timeframe-minutes", 5),
        horizon_bars=_int_option("--horizon-bars", 12),
    )


def historical_bar_archive(start_date: str) -> bool:
    symbol = _str_option("--symbol", "")
    if not symbol and len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        symbol = sys.argv[3]
    end_date = _str_option("--end-date", start_date)
    cache_dir_text = _str_option("--cache-dir", "")
    return run_historical_bar_archive(
        start_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        end_date=end_date,
        cache_dir=Path(cache_dir_text) if cache_dir_text else None,
        build_patterns="--no-patterns" not in sys.argv,
        horizon_bars=_int_option("--horizon-bars", 20),
        dry_run="--dry-run" in sys.argv,
    )


def historical_bar_coverage(start_date: str | None = None) -> bool:
    date_arg = start_date
    if date_arg in {"today", "current"}:
        date_arg = None
    end_date = _str_option("--end-date", "")
    return run_historical_bar_coverage(
        base_dir=BASE_DIR,
        start_date=date_arg,
        end_date=end_date or None,
        min_days=_int_option("--min-days", 252),
        min_symbols=_int_option("--min-symbols", 20),
    )


def historical_bar_progress(start_date: str | None = None) -> bool:
    date_arg = start_date
    if date_arg in {"today", "current"}:
        date_arg = None
    end_date = _str_option("--end-date", "")
    return run_historical_bar_progress(
        base_dir=BASE_DIR,
        start_date=date_arg,
        end_date=end_date or None,
        min_days=_int_option("--min-days", 252),
        min_symbols=_int_option("--min-symbols", 20),
        limit=_int_option("--limit", 15),
    )


def historical_bar_readiness(start_date: str | None = None) -> bool:
    date_arg = start_date
    if date_arg in {"today", "current"}:
        date_arg = None
    end_date = _str_option("--end-date", "")
    return run_historical_bar_readiness(
        base_dir=BASE_DIR,
        start_date=date_arg,
        end_date=end_date or None,
        min_days=_int_option("--min-days", 252),
        min_symbols=_int_option("--min-symbols", 20),
        max_feature_missing_pct=float(_str_option("--max-feature-missing-pct", "5.0")),
        include_db_quality="--include-db-quality" in sys.argv,
        include_duplicate_scan="--include-duplicate-scan" in sys.argv,
        quality_symbol_limit=_int_option("--quality-symbol-limit", 0),
        db_quality_mode=_str_option("--db-quality-mode", "sample"),
        sample_rows_per_symbol=_int_option("--sample-rows-per-symbol", 2000),
        limit=_int_option("--limit", 15),
    )


def ml_dataset_export(start_date: str) -> bool:
    end_date = start_date
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        end_date = sys.argv[3]
    output_text = _str_option("--output", "")
    return run_ml_dataset_export_check(
        start_date,
        end_date=end_date,
        base_dir=BASE_DIR,
        output_path=Path(output_text) if output_text else None,
        output_format=_str_option("--format", "jsonl"),
        include_incomplete="--include-incomplete" in sys.argv,
        min_rows=_int_option("--min-rows", 500),
        min_symbols=_int_option("--min-symbols", 20),
        max_rows=(_int_option("--max-rows", 5000) or None),
        full_manifest="--full-manifest" in sys.argv,
    )


def historical_bar_models() -> bool:
    return run_historical_bar_model_readiness(
        min_rows=_int_option("--min-rows", 5000),
        min_symbols=_int_option("--min-symbols", 59),
        min_accuracy=float(_str_option("--min-accuracy", "0.50")),
        stale_days=_int_option("--stale-days", 30),
        prune="--prune" in sys.argv,
        dry_run="--execute-prune" not in sys.argv,
        keep_per_label=_int_option("--keep-per-label", 2),
        limit=_int_option("--limit", 12),
    )


def historical_bar_paper_strategy(symbol: str) -> bool:
    return run_historical_bar_paper_strategy_report(
        symbol=symbol,
        action=_str_option("--action", "buy"),
    )


def historical_bar_paper_validation(start_date: str) -> bool:
    thresholds_raw = _str_option("--thresholds", "")
    thresholds = None
    if thresholds_raw:
        thresholds = []
        for part in thresholds_raw.split(","):
            try:
                thresholds.append(float(part.strip()))
            except ValueError:
                continue
    return run_historical_bar_paper_validation(
        base_dir=BASE_DIR,
        start_date=start_date,
        end_date=_str_option("--end-date", date.today().isoformat()),
        label_target=_str_option("--label-target", "triple_barrier_label"),
        rows_per_symbol=_int_option("--rows-per-symbol", 250),
        limit=_int_option("--max-rows", 30000),
        threshold=float(_str_option("--threshold", "65.0")),
        thresholds=thresholds or None,
    )


def historical_bar_walk_forward(start_date: str) -> bool:
    return run_historical_bar_walk_forward(
        base_dir=BASE_DIR,
        start_date=start_date,
        end_date=_str_option("--end-date", date.today().isoformat()),
        label_target=_str_option("--label-target", "triple_barrier_label"),
        rows_per_symbol=_int_option("--rows-per-symbol", 250),
        limit=_int_option("--max-rows", 30000),
        threshold=float(_str_option("--threshold", "65.0")),
        folds=_int_option("--folds", 5),
    )


def historical_bar_validation(start_date: str) -> bool:
    return run_historical_bar_validation(
        base_dir=BASE_DIR,
        start_date=start_date,
        end_date=_str_option("--end-date", date.today().isoformat()),
        label_target=_str_option("--label-target", "triple_barrier_label"),
        rows_per_symbol=_int_option("--rows-per-symbol", 250),
        limit=_int_option("--max-rows", 20000),
        min_bucket_rows=_int_option("--min-bucket-rows", 50),
        print_limit=_int_option("--limit", 30),
    )


def monday_readiness() -> bool:
    return run_monday_readiness_check(
        base_dir=BASE_DIR,
        min_historical_symbols=_int_option("--min-historical-symbols", 59),
    )


def exit_intelligence(start_date: str) -> bool:
    end_date = start_date
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        end_date = sys.argv[3]
    return run_exit_intelligence_summary(
        base_dir=BASE_DIR,
        start_date=start_date,
        end_date=end_date,
        limit=_int_option("--limit", 12),
    )


def sqlite_ownership() -> bool:
    return run_sqlite_ownership_report(base_dir=BASE_DIR)


def operator_intelligence(target_date: str) -> bool:
    return run_operator_intelligence_dashboard(
        base_dir=BASE_DIR,
        target_date=target_date,
    )


def learning_readiness(start_date):
    end_date = None
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        end_date = sys.argv[3]
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_learning_readiness(
        start_date,
        end_date=end_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_feature_sample_size=_int_option("--feature-min-sample-size", 30),
        min_pattern_sample_size=_int_option("--pattern-min-sample-size", 30),
        min_calibration_sample_size=_int_option("--calibration-min-sample-size", 5),
        full_readiness_target=_int_option("--full-readiness-target", 750),
    )


def learning_effectiveness(start_date):
    end_date = None
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        end_date = sys.argv[3]
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_learning_effectiveness(
        start_date,
        end_date=end_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_feature_sample_size=_int_option("--feature-min-sample-size", 30),
        min_pattern_sample_size=_int_option("--pattern-min-sample-size", 30),
        min_calibration_sample_size=_int_option("--calibration-min-sample-size", 5),
        full_readiness_target=_int_option("--full-readiness-target", 750),
    )


def active_learning(start_date):
    end_date = None
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        end_date = sys.argv[3]
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_active_learning_integration(
        start_date,
        end_date=end_date,
        base_dir=BASE_DIR,
        symbol=symbol,
    )


def learning_artifacts(target_date):
    return run_learning_artifact_consumption(
        target_date,
        base_dir=BASE_DIR,
    )


def rollout_contract(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_rollout_contract_report(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_sample_size=_int_option("--min-sample-size", 30),
    )


def ai_intelligence_review(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_ai_intelligence_review(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        samples=_int_option("--samples", 10),
    )


def setup_breakdown(target_date: str) -> bool:
    return run_setup_breakdown(target_date, base_dir=BASE_DIR)


def peak_bucket_report(target_date: str | None = None) -> bool:
    return run_peak_bucket_report(target_date, base_dir=BASE_DIR)


def winner_became_loser(target_date: str) -> bool:
    return run_winner_became_loser(target_date, base_dir=BASE_DIR)


def conviction_stack_report(target_date: str) -> bool:
    return run_conviction_stack_report(target_date, base_dir=BASE_DIR)


def _int_option(name: str, default: int = 0) -> int:
    if name not in sys.argv:
        return default
    idx = sys.argv.index(name)
    if idx + 1 >= len(sys.argv):
        return default
    try:
        return int(sys.argv[idx + 1])
    except Exception:
        return default


def _float_option(name: str, default: float = 0.0) -> float:
    if name not in sys.argv:
        return default
    idx = sys.argv.index(name)
    if idx + 1 >= len(sys.argv):
        return default
    try:
        return float(sys.argv[idx + 1])
    except Exception:
        return default


def conviction_persistence_health(target_date: str) -> bool:
    return run_conviction_persistence_health(
        target_date,
        base_dir=BASE_DIR,
        samples=_int_option("--samples", 0),
    )


def buy_opportunity_report(target_date: str) -> bool:
    return run_buy_opportunity_report(target_date, base_dir=BASE_DIR)


def claude_context_audit(target_date: str) -> bool:
    return run_claude_context_audit(target_date, base_dir=BASE_DIR)


def advisory_authority_report(target_date: str) -> bool:
    return run_advisory_authority_report(target_date, base_dir=BASE_DIR)


def paper_learning_authority(target_date: str) -> bool:
    return run_paper_learning_authority_report(target_date, base_dir=BASE_DIR)


def cross_layer_verification(target_date: str) -> bool:
    return run_cross_layer_verification_report(target_date, base_dir=BASE_DIR)


def point_in_time_archive(target_date: str) -> bool:
    reason = "operator_snapshot"
    if "--reason" in sys.argv:
        idx = sys.argv.index("--reason")
        if idx + 1 < len(sys.argv):
            reason = sys.argv[idx + 1]
    return run_point_in_time_archive(target_date, base_dir=BASE_DIR, reason=reason)


def research_export(target_date: str) -> bool:
    return run_research_export(
        target_date,
        base_dir=BASE_DIR,
        limit=_int_option("--limit", 0) or None,
    )


def shadow_predictions(target_date: str) -> bool:
    return run_shadow_prediction_report(target_date, base_dir=BASE_DIR)


def database_backups() -> bool:
    return run_database_backup_report(
        base_dir=BASE_DIR,
        max_age_hours=_float_option("--max-age-hours", 30.0),
    )


def jobs_status(job_name_filter: str | None = None) -> bool:
    """Print latest-run-per-job status table from the job_runs ledger."""
    from repositories.job_runs_repo import JobRunsRepository
    from services.job_runs_service import JobRunsService

    print()
    print("=" * 72)
    print("  Job Run Status — latest run per cron job")
    print("=" * 72)

    db_path = BASE_DIR / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    svc = JobRunsService(JobRunsRepository(db_path))
    rows = svc.job_status_table()

    if job_name_filter:
        rows = [r for r in rows if job_name_filter.lower() in (r.get("job_name") or "").lower()]

    if not rows:
        print("[WARN] no job_runs rows found — jobs may not have run yet")
        return False

    failures = [r for r in rows if r["status"] == "FAIL"]

    print(f"\n  {'job':<40} {'status':<8} {'age':>7} {'dur':>7} {'rows':>6} {'warn':>5}")
    print("  " + "-" * 70)
    for r in rows:
        age = f"{r['age_min']:.0f}m" if r["age_min"] is not None else "-"
        dur = f"{r['duration_sec']:.1f}s" if r["duration_sec"] is not None else "-"
        rows_w = str(r["rows_written"]) if r["rows_written"] is not None else "-"
        warn = str(r["warnings_count"]) if r["warnings_count"] else "-"
        marker = "!" if r["status"] == "FAIL" else " "
        print(
            f"{marker} {r['job_name']:<40} {r['status']:<8} {age:>7} {dur:>7} {rows_w:>6} {warn:>5}"
        )

    print()
    if failures:
        print(
            f"[WARN] {len(failures)} job(s) last run failed: {', '.join(r['job_name'] for r in failures)}"
        )
        return False

    print(f"[OK] {len(rows)} jobs shown — no recent failures")
    return True


def main():
    env_loaded = load_env_file()
    print(f"env_file_loaded={env_loaded}")

    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2

    command = sys.argv[1].lower()
    target_date = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()
    if target_date.startswith("--"):
        target_date = date.today().isoformat()

    command_spec = OPS_COMMAND_SPECS.get(command)
    if command_spec is not None:
        ok = command_spec.run(globals(), build_command_args(sys.argv, target_date))
        return 0 if ok else 1

    if command == "historical-bar-retry-plan":
        args = [
            "pipeline/historical_bar_retry_missing.py",
            "--start-date",
            target_date,
        ]
        end_date = _str_option("--end-date", "")
        if end_date:
            args.extend(["--end-date", end_date])
        for option in ("--min-days", "--max-symbols", "--manifest-limit"):
            value = _str_option(option, "")
            if value:
                args.extend([option, value])
        if "--execute" in sys.argv:
            args.append("--execute")
        if "--json" in sys.argv:
            args.append("--json")
        return 0 if run("Historical Bar Retry Plan", args) else 1

    if command == "premarket":
        return run_premarket_bundle(
            target_date=target_date,
            run=run,
            run_report=run_report,
            script=_script,
            print_section=_print_section,
        )

    if command == "all":
        return run_all_bundle(
            target_date=target_date,
            run=run,
            run_report=run_report,
            script=_script,
            print_section=_print_section,
        )

    # In-process report dispatch — no subprocess overhead.
    if command in REPORT_COMMANDS:
        _print_section(command.title())
        ok = run_report(command, target_date)
        return 0 if ok else 1

    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print()
        print(__doc__.strip())
        return 2

    script = COMMANDS[command][0]
    extra = COMMANDS[command][1:]

    if command == "post":
        args = [script] + extra + [target_date]
    else:
        args = [script] + extra

    ok = run(command.title(), args)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
