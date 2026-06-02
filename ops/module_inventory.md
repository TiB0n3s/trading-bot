# Module Inventory

Purpose: clarify which package areas affect the current paper session, which are
scheduled/ops support, and which are research scaffolding.

## Live Runtime

These modules are imported by the Flask/Gunicorn webhook path or broker path.

- `execution/`
  - `execution.order_policy` is imported by `broker.py`.
  - Used for buy quantity, bracket price calculation, and cash order cap
    comparison.
- `risk/`
  - `risk.account_risk`, `risk.live_guards`, and `risk.macro_policy` are
    imported by `app.py`.
  - Current role is mostly status/compare/live-guard visibility.
  - `risk.exposure` exists as helper scaffolding and is not yet the main live
    exposure path.
- `strategy/`
  - `strategy.strategy_engine` is imported by `app.py` in observe mode.
  - It is not a live decision authority.
- `data_layer/`
  - `data_layer.ledger` is imported by `app.py` for read-only ledger/status
    visibility.
  - It is not yet the DB write abstraction.

## Scheduled Intelligence

These modules are used by cron jobs and session readiness workflows.

- `market_intelligence/`
  - Used by `pre_market_research_data.py` for deterministic market context.
  - Used by `collect_and_score_events.py` for event scoring, context updates,
    and observe-only predictions.
  - `experience_model.py` writes `daily_symbol_predictions`; these remain
    observe-only.
- `services/canonical_intelligence_service.py`
  - Builds canonical decision intelligence for snapshots and replay.
  - Includes observe-only `analytics_state` from the AI analytics toolkit.
- `services/live_features_service.py`
  - Writes feature snapshots and, when `TIMESCALE_DB_URI` is set, mirrors
    compact ticks to optional TimescaleDB storage.
  - Timescale mirroring has no trade authority.

## Ops Reporting

- `ops/`
  - Runbooks, checklists, QA automation, and local evidence.
  - Does not run inside the trading runtime unless an operator invokes it.
- `ops_check.py`
  - Read-only operator reports and wrappers.
  - Some wrapped commands may call external APIs, but the added QA/reporting
    checks do not place orders or change trading behavior.

## Research Only

- `analytics_ext/`
  - Used by `replay_report.py`.
  - Research/replay support, not Tuesday live decision flow.
- `ml/`
  - Planned research platform area for dataset specs, experiments, and model
    registry conventions.
  - No model in this directory should affect runtime decisions without an
    explicit future promotion process.
- Root AI analytics CLIs
  - `ai_dependency_status.py` checks optional heavy dependencies.
  - `score_financial_sentiment.py` scores text through lexicon fallback or
    optional FinBERT.
  - `train_supervised_predictions.py` writes optional supervised research
    artifacts.
  - `train_regime_model.py` writes optional HMM regime research artifacts.
  - `timescale_smoke_test.py` verifies optional Timescale schema/write access.
  - `risk_lockout.py` inspects or changes persistent lockout state.
- AI analytics services
  - `services/analytics_method_service.py` summarizes predictive,
    descriptive, diagnostic, and prescriptive context.
  - `services/portfolio_ai_toolkit_service.py` holds per-symbol portfolio,
    correlation, macro, event, and external-workflow profiles.
  - `services/technical_feature_engineering_service.py`,
    `services/financial_sentiment_service.py`,
    `services/regime_switching_service.py`,
    `services/supervised_prediction_training_service.py`, and
    `services/timescale_tick_writer_service.py` support research/training or
    optional storage paths.
  - `services/regime_risk_protocol_service.py`,
    `services/dashboard_alert_service.py`,
    `services/persistent_lockout_service.py`, and
    `services/async_ai_pipeline_architecture_service.py` expose safety,
    alerting, state, and architecture context. They do not place orders.

## Naming Risks To Resolve After Tuesday

- Root `setup_classifier.py` and `strategy/setup_classifier.py` coexist.
- The live deterministic `prediction_gate` legacy fields are now documented as
  deterministic signal-quality fields. Actual ML/database predictions are
  surfaced separately as `ml_prediction_*` compare-only fields from
  `prediction_cache.py`.
- Some SQL access remains in `app.py` rather than `db.py`/`data_layer`.

## Integration Targets

1. Extract signal-processing logic from `app.py` behind tests.
2. Move exposure checks into `risk/exposure.py` deliberately.
3. Pick one setup-classifier path and deprecate or merge the other.
4. Consolidate durable DB access into `db.py` or `data_layer/`.
5. Keep ML outputs observe-only until feature, label, and matched-trade data
   coverage is strong enough for validation.
6. Wire persistent lockout state into live buy/order paths only if explicitly
   requested, tested, logged, and guarded by default-off config.
