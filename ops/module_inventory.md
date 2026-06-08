# Module Inventory

Purpose: identify which modules affect live trading, which are scheduled
support, which are operator/reporting tools, and which are research-only.

## Live Runtime

- `app.py`
  - Deployed Flask compatibility root: startup entry point, runtime context,
    container selection, and `process_signal()` compatibility.
  - Must not own trading policy, broker calls, SQL, or setup classification.
- `src/trading_bot/web/app_factory.py`
  - Owns Flask app creation and route registration mechanics.
  - Delegates route payload context to the current runtime compatibility module
    until root `app.py` is reduced to a small shim.
- `services/live_signal_processor.py`
  - Owns live signal orchestration.
  - Calls preflight, context, approval, sizing, execution, and audit services.
- `services/context_builder.py`
  - Builds decision/runtime context.
  - Includes setup quality, prediction context, regime observation, momentum,
    trend, market bias, portfolio, execution-quality, and canonical context
    inputs.
- `services/setup_context_service.py` and `services/setup_engine_service.py`
  - Canonical live setup-quality path.
  - Root `setup_classifier.py` is compatibility-only and must not be imported
    by `app.py`.
- `services/approval_service.py`
  - Owns deterministic approval gates and Claude/confidence normalization.
  - New intelligence families must remain observe-only unless routed through an
    explicit authority path and tests.
- `services/sizing_service.py` and `services/policies/sizing_policy.py`
  - Own final size caps and dominant-limiter attribution.
- `services/execution_service.py`, `services/execution_adapters.py`,
  `services/broker_service.py`, and `broker.py`
  - Own final safety checks, quote/spread checks, broker abstraction, and order
    submission.
- `position_manager.py` and `position_momentum_monitor.py`
  - Service/repository-backed exit and position-monitoring entrypoints.

## Scheduled Intelligence

- `pre_market_research_data.py`
  - Deterministic market-context generation through
    `services/pre_market_research_service.py`.
- `collect_and_score_events.py`
  - Event collection/scoring and market-context overlay.
  - Source reliability and context validation are reported through
    `ops_check.py`.
- `live_features.py`, `session_momentum.py`, `rolling_momentum.py`,
  `label_v1_builder.py`
  - Thin or service-backed cron entrypoints for intraday and post-session
    feature/state production.
- `services/canonical_intelligence_service.py`,
  `services/canonical_exit_service.py`,
  `services/lifecycle_analysis_service.py`
  - Immutable entry/exit/lifecycle substrate for audit, replay, reports, and ML
    exports.
- `services/job_runs_service.py` and `job_runner.py`
  - Durable cron/job ledger and runtime-health substrate.

## Reporting And Ops

- `ops_check.py`
  - Main operator report router.
  - Reports should read through services/repositories, not direct SQL or
    direct market-data calls.
- `*_report.py`, `*_builder.py`, and `ops/tuesday_qa_runner.py`
  - Report, labeling, QA, and post-session tools.
  - They must not change live policy without an explicit config/policy artifact
    path.
- `live_score_monitor.py` and `intelligence_status.py`
  - Standalone read-only operator tools.
  - They are not cron/runtime dependencies.
- `risk_lockout.py`, `regime_status.py`, `ai_dependency_status.py`,
  `timescale_smoke_test.py`
  - Operator/status tools for optional infrastructure or risk-state inspection.

## Research Only

- `ml_platform/`
  - Offline/research platform, staged contracts, dataset builders, validation,
    replay, and dormant serving provider.
  - No `ml_platform` output should affect live decisions without explicit
    promotion, authority-leak tests, and operator config.
- `analytics_ext/`
  - Replay/attribution support.
- `strategy/trade_scorer.py` and `strategy/setup_classifier.py`
  - Research/replay-oriented strategy scoring/classification.
  - Not live authority.
- `train_supervised_predictions.py`, `train_regime_model.py`,
  `score_financial_sentiment.py`
  - Research/training/operator utilities. Artifacts are observe-only until a
    promotion contract approves otherwise.

## Compatibility-Only Modules

- `setup_classifier.py`
  - Legacy deterministic setup classifier retained for historical/manual
    imports.
  - Live setup quality comes from `services.setup_engine_service`.
- `prediction_cache.py`, `prior_session_context.py`, `session_momentum.py`,
  `live_features.py`, `bot_events.py`
  - Public compatibility wrappers over service/repository implementations.

## Local Artifacts

Runtime logs, rotated logs, `session_logs/`, and timestamped `.bak_*` files are
local evidence or backup artifacts, not source. They should remain untracked and
can be cleaned with `ops/clean_local_artifacts.sh` when no longer needed.

## Current Integration Targets

1. Keep `app.py` composition/runtime-context only through architecture tests.
2. Keep root `setup_classifier.py` out of live wiring.
3. Continue moving report/script reads through services and repositories.
4. Treat ML/regime/analytics additions as observe-only unless explicit
   authority tests and rollout contracts promote them.
5. Use canonical entry/exit/lifecycle snapshots as the default analysis and ML
   substrate.
