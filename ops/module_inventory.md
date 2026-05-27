# Module Inventory

Purpose: clarify which package areas affect the Tuesday paper session, which are
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

These modules are used by cron jobs and Tuesday readiness workflows.

- `market_intelligence/`
  - Used by `pre_market_research_data.py` for deterministic market context.
  - Used by `collect_and_score_events.py` for event scoring, context updates,
    and observe-only predictions.
  - `experience_model.py` writes `daily_symbol_predictions`; these remain
    observe-only.

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

## Naming Risks To Resolve After Tuesday

- Root `setup_classifier.py` and `strategy/setup_classifier.py` coexist.
- The live deterministic `prediction_gate` legacy fields are now documented as
  deterministic signal-quality fields. Actual ML/database predictions are
  surfaced separately as `ml_prediction_*` compare-only fields from
  `prediction_cache.py`.
- Some SQL access remains in `app.py` rather than `db.py`/`data_layer`.

## Post-Tuesday Integration Targets

1. Extract signal-processing logic from `app.py` behind tests.
2. Move exposure checks into `risk/exposure.py` deliberately.
3. Pick one setup-classifier path and deprecate or merge the other.
4. Consolidate durable DB access into `db.py` or `data_layer/`.
5. Keep ML outputs observe-only until feature, label, and matched-trade data
   coverage is strong enough for validation.
