# ML Platform Roadmap

This bot should become an ML research and decision-support platform before it
becomes an ML-driven trading system.

## Current stance

- Paper trading remains the runtime mode.
- Prediction outputs stay observe-only.
- No model should place orders, loosen risk controls, or override broker/order
  safeguards.
- Any future prediction influence must be paper-only, environment-controlled,
  logged, reversible, and limited to soft risk reduction until validated.

## Near-term foundation

1. Keep deterministic intelligence generation stable.
2. Monitor data collection with `dataset-health`, `feature-health`, and
   `feature-watch`.
3. Track rejected signals with `rejection-summary`.
4. Track order/fill integrity with `order-health`.
5. Preserve clean Tuesday session evidence before structural refactors.

## Platform Layers

### Data Governance Layer

Goal: prevent leakage, stale features, schema drift, and unverifiable datasets.

Current state:

- `ml_platform.governance` defines first-class contracts for leakage policy,
  decision snapshots, dataset manifests, label taxonomy, fill confidence,
  abstention, sample gates, baselines, calibration, drift checks, kill switches,
  and model-card non-authority.
- `dataset-manifest`, `governance-contract`, `label-taxonomy`,
  `model-card-template`, and `env-policy` CLI commands are staged as read-only
  research/operator tools.

Required rules:

- Every canonical dataset row needs `feature_available_at`,
  `feature_generated_at`, `feature_age_seconds`, `source`, `is_stale`, and
  `staleness_reason`.
- Training features may only include information available at or before the
  decision cutoff. The platform must explicitly track what was knowable at
  `signal_time`, `order_decision_time`, `fill_time`, `exit_time`,
  `end_of_day`, and `next_session_open`.
- Anything learned after the relevant decision timestamp is excluded from
  feature columns, including matched outcomes, post-decision predictions,
  edited/future market context, position-manager exits, trend/timing reports,
  and post-session labels.
- Every signal/order attempt eventually needs an immutable
  `decision_snapshot` record with signal id, timestamp, symbol, action, price,
  market context version, macro regime, risk multiplier, setup label/score,
  trend state, momentum state, prediction version, risk-gate outputs, final
  decision, rejection reason, order id, git SHA, and env profile hash.
- Dataset comparisons require a manifest with dataset id, created time, source
  DB path/hash, query version, label version, feature version, row count, symbol
  count, date range, excluded-row reason counts, and git SHA.

Remaining:

- Add schema/migration management before structural DB refactors.
- Add durable decision snapshots after Tuesday's session is preserved.
- Add rejected-signal forward returns and stale-context quality gates.

### Dataset Layer

Goal: canonical tables/views for signals, trades, fills, market context,
features, labels, predictions, and outcomes.

Current state:

- Tables exist for core runtime state, feature snapshots, labels, intelligence
  context/events/predictions, trades, fills, matched trades, and bot events.
- `export_ml_dataset.py` exports a first supervised dataset.
- `ml_platform.datasets` profiles coverage.
- `ml_platform.brain_features` exports deterministic bot-brain features.

Remaining:

- Define canonical SQL views or builder contracts for signals, fills, outcomes,
  and order-time decision context.
- Freeze label definitions before training claims.
- Use label taxonomy v1 rather than a single win/loss target. Labels should
  separate entry quality, MFE/MAE, time to profit/drawdown, 15/30/60 minute
  returns, stop/take-profit touch, late entry, churn, bad fill, and correct
  rejection.
- Mark fill confidence using the truth hierarchy: Alpaca order/fill data,
  fill stream, fill poller, trades table, then synthetic matcher.

### Experiment Layer

Goal: versioned scoring policies and prediction experiments. Every model/rule
run should record inputs, code version, config, output, and outcome.

Current state:

- `ml_platform.experiments` creates local experiment scaffolds with config,
  metrics, feature columns, and notes.
- Experiment artifacts are ignored by default unless intentionally promoted.

Remaining:

- Record git SHA, dataset hash, config hash, and output hash.
- Convert the existing similarity model into versioned model/rule `v0`.

### Evaluation Layer

Goal: backtests, walk-forward validation, calibration reports, confusion
matrices, PnL attribution, and "would this have improved decisions?" reports.

Current state:

- Existing reports cover attribution, prediction validation, trend context,
  signal timing, policy backtest, missed opportunity, and context/trade joins.
- `ml_platform.evaluation` defines the required evaluation contract.

Remaining:

- Unify these reports under one canonical evaluation runner.
- Add walk-forward splits and calibration outputs.
- Add explicit decision-delta reports comparing current behavior vs model-aided
  behavior.
- Keep prediction quality separate from policy usefulness. Reports should ask
  whether prediction correlated with outcome, whether acting on it would improve
  PnL/drawdown/bad entries, whether it would reject too many winners, whether it
  would concentrate risk, and whether it would conflict with hard controls.

### Replay Layer

Goal: compare current bot decisions against candidate model/policy behavior
without touching runtime trading.

Current state:

- `ml_platform.replay` and `python3 -m ml_platform.cli replay-decisions` define
  the output contract for shadow replay. The command is scaffold-only today and
  has no runtime effect.

Required outputs:

- same decision count,
- changed decision count,
- approved fewer,
- approved more,
- avoided losers,
- missed winners,
- net simulated delta,
- worst changed decision,
- best changed decision.

Required inputs:

- immutable decision snapshots,
- rejected-signal forward returns,
- baseline policies,
- realistic cost/slippage assumptions.

Baselines:

- always approve,
- always reject,
- current bot policy,
- symbol historical average,
- setup-label average,
- macro-regime average,
- previous model version,
- randomized policy with the same trade count.

Friction assumptions:

- spread estimate,
- slippage estimate,
- partial fill handling,
- commission placeholder,
- latency assumption,
- market order vs limit order behavior,
- stop-loss/take-profit execution approximation.

### Model Registry

Goal: simple JSON/YAML model cards plus artifact files. Track status such as
`observe_only`, `warn_only`, `paper_gate`, and `live_candidate`.

Current state:

- `ml_platform.registry` stores JSON model metadata.
- Current allowed statuses include `research`, `observe_only`, `warn_only`,
  `paper_gate`, `live_candidate`, `shadow`, `paper_soft`, and `retired`.

Remaining:

- Add model-card templates and promotion review checklist.
- Require evaluation artifact links before any status beyond `observe_only`.
- Every model card must explicitly say the model does not place orders, does
  not override hard risk controls, does not increase size without later
  promotion, is invalid outside listed symbols/regimes/date ranges, and must
  abstain on stale or missing features.

### Promotion Governance Layer

Goal: make model promotion boring, slow, reversible, and evidence-based.

Current state:

- Governance contracts now define minimum sample gates, calibration buckets,
  abstention output shape, drift checks, kill-switch defaults, and model-card
  non-authority.

Promotion gates:

- minimum 30 evaluated signals per symbol before symbol-level claims,
- minimum 100 evaluated signals per regime before regime-level claims,
- minimum 20 rejected-signal forward outcomes before rejection-policy claims,
- minimum 50 matched trades before sizing-policy claims,
- calibrated confidence buckets before confidence can control risk,
- drift checks for feature distributions, symbol universe, macro regime,
  prediction confidence, approval/rejection mix, PnL attribution, and fill
  quality.

Default kill switches:

- `ML_PLATFORM_ENABLED=false`
- `ML_PREDICTION_PROVIDER_ENABLED=false`
- `ML_STATUS_EXPOSURE_ENABLED=false`
- `ML_MODEL_ID=`
- `ML_MODEL_MAX_AGE_SECONDS=`

Model output must support abstention:

```json
{
  "prediction": "avoid_entry",
  "confidence": 0.61,
  "abstain": false,
  "abstain_reason": null
}
```

Promotion remains blocked if the model cannot explain top positive features,
top negative features, missing features, similar historical cases, regime
match/mismatch, calibration bucket, and abstention status.

### Serving Layer

Goal: read-only prediction service used by `app.py`, initially only for logging
and dashboards.

Current state:

- `ml_platform.serving` defines a dormant read-only `PredictionProvider`
  interface and SQLite implementation.
- It is not imported by `app.py` yet.

Remaining:

- After Tuesday, optionally expose provider output in `/status` only.
- Keep all runtime influence off until paper evidence supports promotion.
- Serving must degrade to no prediction if disabled, stale, missing, or failed;
  it must never block signal processing.

### Operator UI/API

Goal: status, prediction explanations, model comparison, daily readiness, and
risk review.

Current state:

- `/status`, `ops_check.py`, Tuesday QA automation, and read-only reports cover
  much of the operator surface.

Remaining:

- Add model comparison and daily ML readiness reports.
- Add model-card status to operator output once real models exist.

## Recommended Phases

### Phase 1: Stabilize Foundation

- Split `app.py` into webhook handling, signal validation, context building,
  risk checks, order execution, and logging after Tuesday.
- Add formal schema/migration management instead of scattered runtime table
  creation. This includes a schema version table, migration files, migration
  status command, backup before migration, rollback notes, and idempotent
  checks.
- Make local setup reproducible with `pyproject.toml` or
  `requirements-dev.txt`.
- Add sample/synthetic `market_context.json` fixtures for tests.
- Add regression fixtures from known bad cases: suspect quote/excessive spread,
  late entry, sell-to-buy churn, macro cap full, affordability rejection, price
  sanity failure, earnings hard avoid, missing/stale market context, synthetic
  matched exit, and broker fill mismatch.

Status: partially started with safety docs, ops checks, ML scaffolding, and
readiness automation. Structural refactor is intentionally deferred until after
Tuesday.

### Phase 2: Make ML Loop Real

- Define one canonical training dataset builder.
- Freeze label definitions.
- Store model/evaluation artifacts under `ml_platform/` and `ml/`.
- Convert the existing similarity model into model `v0` with versioned config.
- Add walk-forward validation before any live influence.
- Add rejected-signal outcome tracking with 5/15/30/60 minute, EOD, MFE, and
  MAE forward returns.

Status: scaffolded, not train-ready. Waiting on post-rebuild
`feature_snapshots`, `labeled_setups`, and matched outcomes.

### Phase 3: Platformize Decisions

- Introduce `PredictionProvider`.
- Keep live behavior observe-only.
- Add dashboards/reports comparing current decisions vs prediction-assisted
  decisions.
- Promote only after evidence: observe-only -> warn-only -> soft modifier ->
  guarded paper gate.

Status: provider interface scaffolded only; no `app.py` integration yet.

### Phase 4: Productize If Desired

- Add multi-strategy support.
- Add experiment comparison UI.
- Add model registry deployment states.
- Add audit logs, permissions, and safer config management.

Status: future.

## Bot Brain Integration Layer

The first integration point is offline feature generation from existing bot
intelligence, not live model serving.

Reusable logic staged for ML:

- `setup_engine.classify_setup`: converts intraday feature snapshots into
  deterministic setup labels/scores.
- `daily_symbol_context`: premarket context, risk, entry quality, and aggregated
  event scores.
- `daily_symbol_events`: catalyst/event coverage and future event embeddings.
- `daily_symbol_predictions`: existing observe-only similarity predictions.
- `market_intelligence.tape_reader`: future intraday tape labels from bar data.
- `strategy.trade_scorer`: future shadow-only trader-brain score, with leakage
  controls before historical use.
- `decision_context` / `decision_policy`: future policy-replay features, not
  live authority.

## Trend And Momentum Use

Existing order intelligence:

- `app.py` builds trend state from signal history and stores trend fields on
  trade rows.
- `app.py` uses short momentum, session momentum, setup observation, and
  prediction-gate diagnostics in decision context and audit rows.
- `session_momentum.py`, `rolling_momentum.py`, and
  `position_momentum_monitor.py` feed session/position risk visibility.
- `market_intelligence.experience_model` blends trend/timing lessons into
  observe-only `daily_symbol_predictions`.

ML platform use:

- `feature_snapshots` include trend direction/strength plus short-horizon
  return, relative strength, VWAP distance, and volume features.
- `ml_platform.brain_features` now exports those trend/momentum fields beside
  setup labels, context, events, and predictions.
- Future dataset builders should add order-time `trades.session_momentum_*`
  fields and rolling-momentum state with leakage checks.
- Trend/momentum features must carry availability timestamps. A trend report
  produced after an order decision is evaluation evidence, not a training
  feature for that decision.

Current command:

```bash
python3 -m ml_platform.cli export-brain-features \
  --date 2026-05-26 \
  --output /tmp/brain_features_2026-05-26.csv
```

Promotion remains blocked until the integration contract allows it:

```bash
python3 -m ml_platform.cli integration-contract
```

## Refactor sequence after Tuesday

1. Extract signal-processing logic from `app.py` behind tests.
2. Add typed context/result objects around the extracted seam.
3. Move restart-sensitive globals behind a durable state manager.
4. Consolidate SQL access into `db.py` after behavior is covered.
5. Add structured logging/report exports where reporting needs it.

## Promotion rule

A model can only move from observe-only to paper-trading influence after it has:

- enough feature and label coverage,
- matched-trade outcome coverage,
- stable out-of-sample validation,
- an explicit rollback plan,
- an environment flag defaulting off,
- operator-visible reports showing what it would have changed.

## Best Next Additions After Tuesday

1. Add schema/migration management.
2. Add immutable decision snapshots.
3. Add `feature_available_at` and `feature_generated_at` fields.
4. Add rejected-signal forward outcome tracking.
5. Define label v1 formally.
6. Add dataset manifest generation to dataset export flow.
7. Convert the similarity model into versioned model `v0`.
8. Build the real `replay-decisions` command.
9. Add calibration and walk-forward evaluation.
10. Only then expose the read-only prediction provider in `/status`.

The biggest missing concept is auditability of what the bot knew at decision
time. Without that, training, evaluation, and promotion can look sophisticated
while still being structurally unreliable.
