# ML Platform Roadmap

This bot should become an ML research and decision-support platform before it
becomes an ML-driven trading system.

## Current stance

- Paper trading remains the runtime mode.
- Prediction outputs remain conservative and evidence-gated.
- No model should place orders, loosen risk controls, or override broker/order
  safeguards.
- Current prediction influence is limited to logged downside size caps for weak
  prediction evidence. Hard prediction blocking remains disabled unless
  explicitly promoted through paper-session validation.
- Any future additional prediction influence must be paper-only,
  environment-controlled, logged, reversible, and limited to soft risk reduction
  until validated.

## Near-term foundation

1. Validate setup health on a clean-feed live paper session.
2. Confirm SIP->IEX fallback health and collapse of setup-policy error counts.
3. Verify conviction-stack persistence with `conviction-persistence-health`.
4. Use `conviction-stack-report`, `peak-bucket-report`, and
   `winner-became-loser` before tuning policy.
5. Tune one policy at a time from measured paper evidence: exit capture,
   weak-entry containment, conviction caps, buy-opportunity sizing, prediction
   authority, then session-momentum caps.

## Explicit Pending Gates Before Broader ML Authority

These items must remain visible because they can quietly corrupt future ML work
or destabilize the webhook path if treated as routine cleanup.

1. Serving latency SLA:
   - Prediction reads must stay outside direct webhook DB access.
   - Current contract: target 25 ms, hard timeout 50 ms, in-memory TTL cache
     loaded outside the webhook path, TTL 60 seconds, fail-open to no
     prediction.
   - A provider timeout/error must never block signal processing or hard risk
     checks.
2. Manual override confounders:
   - `manual_strategy_overrides.json` and `symbol_overrides.json` must be
     timestamped or hashed into dataset manifests.
   - Dataset rows spanning unknown active override periods must be excluded or
     flagged before training.
   - Current manifest contract includes `override_files`,
     `override_state_hash`, and `override_tracking_status`.
3. Architecture-boundary regression risk:
   - `app.py` is now a composition root, and the live signal path is
     service-owned.
   - Temporary architecture allowlists are empty. Do not reintroduce direct DB,
     broker, market-data, or Flask coupling outside approved boundaries.
   - Keep architecture-boundary tests green before and after ML/report changes.
4. Retraining cadence:
   - No automatic retraining by default.
   - First policy: manually reviewed batch retraining after 20 trading sessions
     or after a drift/performance alert.
   - After-close learning should produce retraining-readiness evidence, not
     silently deploy new model artifacts.
5. Existing after-close policy artifacts:
   - `strategy_memory.json`, `portfolio_replacement_memory.json`,
     `excursion_memory.json`, `missed_opportunity_memory.json`, and
     `policy_backtest_summary.json` already influence runtime context/policy.
   - Treat them as `policy_artifact`, not plain reports.
   - Their hashes/mtimes must appear in `/status` and dataset manifests.
   - `run_after_close_learning.sh` must alert on failure so stale artifacts are
     visible before the next session.
   - Writes must be atomic because Flask can read these files while after-close
     learning is running.
   - `POLICY_ARTIFACTS_ENABLED=false` must make live loaders return neutral
     state without file deletion.
6. Conviction persistence:
   - Approved BUY rows must persist final sizing attribution, dominant limiter,
     effective size cap, active-cap state, ML bucket/score, setup action,
     session label, strategy score, and buy-opportunity recommendation.
   - Rejected BUY rows should persist available pre-sizing context, while sizing
     fields are expected only for rows that reached sizing.
7. Cron/job observability:
   - `job_runner.py` is the standard wrapper for write-heavy cron/operator
     jobs. It owns non-blocking locks, lock-busy logging, command output
     redirection, and durable `job_runs` rows with job name, start/end,
     duration, exit code, lock-acquired/skipped state, optional rows written,
     warnings, and artifact paths/hashes.
   - Next observability step: pass real row/warning/artifact metrics from
     individual jobs instead of only command-level status.
8. Runtime/offline feature parity:
   - `ml_platform.feature_parity_contract` defines the first enforced
     runtime/offline feature contract for ML-facing decision features.
   - `tests/test_feature_parity_contract.py` verifies matching field names
     across `decision_snapshots` and `ml_platform.dataset_builder.ROW_COLUMNS`,
     documented null semantics, and point-in-time cutoff rules.
   - Next parity step: expand the contract from the current high-value
     decision features into the canonical intelligence snapshot once that
     snapshot exists.
9. Canonical intelligence snapshot:
   - `canonical_intelligence_v1` is persisted with each decision snapshot as
     JSON plus hash/version.
   - It unifies regime, momentum, trend, event/intelligence, prediction, setup,
     strategy, opportunity, policy-artifact, source timestamp, freshness, and
     confidence state without changing approval or execution behavior.
   - `canonical_exit_v1` is persisted through the exit snapshot substrate with
     lifecycle links back to entry trade ids, decision snapshot ids, entry
     canonical hashes, exit canonical hashes, realized/foregone outcome
     summaries, and compact exit regime/momentum/trend state.
   - `rejected_signal_outcomes` now links counterfactual forward outcomes back
     to decision snapshot ids and canonical intelligence hashes when available.
   - `LifecycleAnalysisService` is the first standard analysis surface joining
     canonical entry decisions, canonical exit snapshots, and rejected-signal
     counterfactual outcomes.
   - Next step: make dataset export and replay consume these canonical objects
     directly instead of reconstructing equivalent state from several columns.

## Platform Layers

### Data Governance Layer

Goal: prevent leakage, stale features, schema drift, and unverifiable datasets.

Current state:

- `ml_platform.governance` defines first-class contracts for leakage policy,
  decision snapshots, dataset manifests, label taxonomy, fill confidence,
  abstention, sample gates, baselines, calibration, drift checks, kill switches,
  counterfactual handling, point-in-time context, demotion, retraining cadence,
  serving latency, override confounders, and model-card non-authority.
- `dataset-manifest`, `governance-contract`, `label-taxonomy`,
  `model-card-template`, and `env-policy` CLI commands are staged as read-only
  research/operator tools.
- `decision_snapshots` records immutable point-in-time decision context for new
  approvals/rejections.
- `feature_snapshots` carries leakage/audit fields required by the governance
  contract.
- Repositories/services own DB and market-data access for runtime files,
  reports, ops checks, ML builders, and backfill/training scripts.
- Architecture tests enforce approved DB, broker, market-data, Flask, policy,
  repository, and report boundaries with empty temporary allowlists.

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
  count, date range, excluded-row reason counts, git SHA, override file hashes,
  override state hash, and override tracking status.

Remaining:

- Continue reducing compatibility wrappers only when grep proves no public
  import surface depends on them.
- Add stale-context quality gates where validation shows they would have
  prevented contaminated rows.
- Keep archiving point-in-time market context and override state before
  historical brain-feature replay is trusted.

### Counterfactual And Selection-Bias Layer

Goal: prevent the platform from learning only what past approvals looked like.

Problem:

- Approved trades have observed outcomes.
- Rejected signals do not have observed trade outcomes unless forward market
  movement is reconstructed.
- A model trained only on approved trades learns "what made approved trades win
  or lose", not "what made a signal worth taking."

Required before training:

- Reconstruct rejected-signal forward returns from point-in-time bar data, or
  explicitly mark any model/report as approved-trade-only and selection-biased.
- Store rejected-signal outcomes for 5/15/30/60 minute returns, EOD return,
  max favorable excursion, and max adverse excursion.
- Evaluate "would this have improved decisions?" against both approved and
  rejected opportunities.

Status: identified as a hard blocker for real model training. The existing
`signal_outcome_builder.py`/bar-data infrastructure should be reviewed after
Tuesday and promoted into the canonical dataset path if suitable.

### Point-In-Time Context Layer

Goal: ensure historical replay uses the context that existed at signal time.

Problem:

- Replaying historical signals through code that calls `load_market_context()`
  can silently use today's `market_context.json`.
- Manual override files can change behavior without appearing as features.
- Symbol-list changes can create survivorship bias.

Required before historical brain-feature training:

- Archive `market_context.json` or equivalent market context by date/timestamp.
- Version `daily_symbol_context`, manual overrides, symbol overrides, and symbol
  universe membership by effective timestamp.
- Add `symbol_universe_version`, active-from/active-to timestamps, and add/remove
  reasons.
- Exclude or flag rows whose override state is unknown.
- Include override state hash/status in every dataset manifest until full
  timestamped override history exists.
- Inject point-in-time context into `strategy.trade_scorer`; do not let replay
  read the live context file.

Status: `strategy.trade_scorer` remains future/shadow-only for ML until this is
implemented.

### Symbol Universe Expansion

Goal: reduce survivorship bias and improve future-forward data coverage without
changing Tuesday's paper-trading behavior.

Promoted to approved collection on 2026-05-26 as
`approved_universe_2026_05_26_internal_bar_expansion_v1`:

- AMZN
- JPM
- TSM
- SNPS
- DELL
- ADSK
- NTAP
- ZS
- PYPL
- SOFI
- PFE
- VZ
- T
- CMCSA
- DKS
- MDB
- OKTA
- BURL

These symbols are intentionally tagged `internal_bar_only`: collect Alpaca
research, session momentum, rolling momentum, live features, and outcomes, but
do not add TradingView alerts. The purpose is to compare bar-derived/internal
candidate quality against the existing alert-driven universe.

Initial auto-buy methodology:

- `auto_buy_manager.py --scope internal` scores internal/bar-only candidates
  from session momentum, latest live feature snapshot/setup, and market context.
- It writes `auto_buy_candidates` and `AUTO_BUY_CANDIDATE` bot events for
  comparison against TradingView-triggered signals.
- Live paper buys are disabled by default and require both `--live` and
  `AUTO_BUY_LIVE_BUYS=true`.
- Current default live sizing, if explicitly enabled, is intentionally small:
  `AUTO_BUY_POSITION_SIZE_PCT=0.50`, `AUTO_BUY_STOP_LOSS_PCT=1.00`, and
  `AUTO_BUY_TAKE_PROFIT_PCT=2.00`.
- Live execution is capped by `AUTO_BUY_MAX_ORDERS_PER_RUN`,
  `AUTO_BUY_MAX_DAILY_ORDERS`, and `AUTO_BUY_COOLDOWN_MINUTES`.
- Before submitting a live paper order, auto-buy cross-checks shared app
  cooldowns, recent-sell churn state, per-symbol app buy count, and
  correlation-cluster exposure. Candidate collection skips closed-market runs
  and the first session buffer window to avoid dead/noisy rows.

Remaining candidates to review after additional paper evidence:

- F
- HBAN
- KEY
- KHC
- CRM
- PDD
- HPQ
- BBY
- DLTR
- GPS
- AEO
- BKE

Candidate cohorts:

- Large-cap liquid: AMZN, JPM, TSM.
- Defensive/dividend: T, VZ, PFE, KHC, CMCSA.
- Low-price higher-volatility: SOFI, HBAN, KEY, F.
- Enterprise/software: ZS, CRM, SNPS, ADSK, MDB, OKTA.
- Retail/consumer discretionary: DKS, BBY, BURL, DLTR, GPS, AEO, BKE.
- Hardware/infrastructure: HPQ, DELL, NTAP.
- International/ecommerce: PDD.

Rules before adding any candidate to live collection or approved trading:

- Record a new `symbol_universe_version`.
- Record active-from timestamp and add reason.
- Backfill or collect enough feature/context/outcome data before making
  symbol-level ML claims.
- Keep the old universe identifiable so historical evaluation does not pretend
  these symbols were always eligible.
- Run post-QA readiness checks before any runtime approved-symbol change.
- Profile feature distributions per symbol, cohort, and
  `symbol_universe_version` before cross-symbol training.
- Keep experience-model similarity matching cohort-aware, or normalize features
  enough to justify cross-cohort comparisons. A SOFI setup should not inherit
  confidence from NVDA-like historical context without evidence.
- Treat cohort labels as hypotheses, not permanent truth. Check whether each
  symbol's realized feature distributions remain cohort-consistent across macro
  regimes before including it in cross-symbol training.
- Run a signal-frequency and signal-quality triage against the current approved
  universe before committing ML research time to candidates. Defensive/dividend
  names such as T, VZ, and PFE may not produce enough clean momentum alerts for
  this bot and can remain candidates indefinitely.

### TradingView Alert Role Review

Goal: decide whether TradingView alerts are adding useful signal or mostly
noise now that Alpaca bar data drives rolling momentum, session momentum,
live feature snapshots, setup classification, and prediction validation.

Near-term posture:

- Keep TradingView alerts connected until enough side-by-side evidence exists.
- Treat TradingView alerts as one external signal source, not as ground truth.
- Build an observe-only internal signal candidate from Alpaca bars using the
  same feature, setup, momentum, and context layers already in the bot.
- Compare TradingView-triggered signals against internal bar-derived signal
  candidates over multiple paper sessions.
- Measure which source better predicts 5m/15m/30m forward returns, approvals,
  rejects, missed opportunities, and avoidable noise.
- If TradingView alerts are mostly rejected or lower-quality than internal
  candidates, demote or disable them and keep only high-conviction alert types.

Promotion rule:

- Do not remove TradingView from the live signal path until the internal signal
  generator has observe-only evidence, operator-visible reports, and a rollback
  path.

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
- Prefer fixed-horizon labels for model training. Realized-PnL labels must carry
  `exit_policy_version` and `position_manager_version` because adaptive exit
  logic changes what "win" means over time.
- `export_ml_dataset.py` defaults to complete fixed-horizon label rows only.
  It excludes unlabeled/incomplete/near-close partial rows from the CSV while
  preserving exclusion counts in the manifest. `--include-incomplete-labels` is
  for audit exports, not training.
- Initial feature-snapshot training targets are `ret_fwd_15m`, `ret_fwd_30m`,
  `max_up_15m`, and `max_down_15m`. `ret_fwd_60m`,
  `max_favorable_excursion`, and `max_adverse_excursion` should be added to the
  feature-snapshot label schema before they are promoted as dataset targets.
- Track class distribution for every target. Accuracy alone is not acceptable
  when labels are imbalanced.

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
- Record override-state hash, symbol-universe version, exit-policy version,
  feature version, label version, and retraining policy.
- Add symbol-cohort awareness to similarity experiments before claims on newly
  added defensive, large-cap liquid, or low-price/high-volatility cohorts.

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
- Use purged walk-forward validation, not naive adjacent splits. Training rows
  temporally close to the test boundary must be purged, and same-symbol rows
  immediately after training windows need an embargo period.
- Surface class imbalance with precision at threshold, winner recall,
  false-reject rate for winners, expected value after friction, balanced
  accuracy, and class distribution.
- Compare against a null no-ML current-bot baseline and the current
  Claude-plus-deterministic-gates system specifically.

### Replay Layer

Goal: compare current bot decisions against candidate model/policy behavior
without touching runtime trading.

Current state:

- `ml_platform.replay` and `python3 -m ml_platform.cli replay-decisions` are
  read-only and have no runtime effect.
- Replay v1 re-runs `evaluate_decision_policy()` against stored
  `decision_snapshots.account_state_json`, joins changed decisions to realized
  `matched_trades` or counterfactual `rejected_signal_outcomes`, and reports
  friction-adjusted decision-delta estimates.
- Hard-gate rejects and policy-relevant rejects are separated in the output.

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
- recovered missed winners,
- introduced losers,
- changed rows with joined outcomes.

Required inputs:

- immutable decision snapshots,
- rejected-signal forward returns,
- baseline policies,
- realistic cost/slippage assumptions.

Baselines:

- always approve,
- always reject,
- null no-ML current bot,
- current bot policy,
- current Claude plus deterministic gates,
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
- purge/embargo settings for temporally correlated signals.

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
- Model cards also need `last_trained_date`, `retraining_policy`,
  `retraining_trigger`, `training_data_end_date`, and demotion/rollback fields.

### Existing Policy Artifact Governance Layer

Goal: bring the pre-existing after-close learning artifacts under governance.

Problem:

- `run_after_close_learning.sh` writes memory artifacts nightly.
- `strategy_memory.py`, `portfolio_replacement_memory.py`,
  `decision_policy.py`, and `decision_context.py` load these artifacts in the
  live runtime path.
- These artifacts can block, size down, or alter live decision context before
  any future ML `PredictionProvider` exists.
- `policy_artifacts.py` registers artifact sets, stores snapshot contents under
  `data_archive/policy_artifacts/`, tracks a known-good pointer, and can roll
  back runtime artifacts with temp-file replacement.
- `run_after_close_learning.sh` registers the completed artifact set as
  known-good after all learning steps finish.

Governed artifacts:

- `strategy_memory.json`
- `portfolio_replacement_memory.json`
- `excursion_memory.json`
- `missed_opportunity_memory.json`
- `policy_backtest_summary.json`

Current controls:

- `/status` exposes read-only hashes, mtimes, generated timestamps, and combined
  state hash under `policy_artifacts`, including registry and known-good status.
- `dataset-manifest` includes policy artifact hashes, registry hash,
  known-good artifact id, and tracking status.
- `run_after_close_learning.sh` logs a critical `AFTER_CLOSE_LEARNING` bot event
  if the run fails before completion.
- Policy artifact writes use temp-file plus `os.replace()` atomic replacement.
- `POLICY_ARTIFACTS_ENABLED=false` makes live loaders return neutral/no learned
  policy influence without deleting artifact files.
- `ops_check.py policy-artifacts` warns if registry entries or the known-good
  pointer are missing.

Remaining:

- Consider mirroring policy artifact set ids into the model registry if model
  and policy-artifact promotion workflows converge.
- Add stricter stale/unexpected hash drift thresholds once normal nightly
  artifact variance is observed.

### Decision Policy Authority Layer

Goal: keep `decision_policy.py` conservative, explicit, and reversible while it
remains under paper-session review.

Current state:

- `decision_policy.py` runs before Claude and can return `block`, `size_down`,
  or `allow` for BUY signals.
- Live authority is explicit in env/status:
  `DECISION_POLICY_AUTHORITY_MODE=paper_only`,
  `DECISION_POLICY_LIVE_BLOCK=true`, and
  `DECISION_POLICY_LIVE_SIZE_DOWN=true` by default.
- `paper_only` means block/size-down authority applies to paper/dry-run modes
  only. Cash modes observe the policy unless an operator explicitly sets
  `DECISION_POLICY_AUTHORITY_MODE=all_modes`.
- The policy exposes `can_increase_size=false` and `can_submit_orders=false`,
  and unit tests assert it does not import/call broker order execution.
- Hard-gate awareness is replay/audit mirroring from `account_state`; app hard
  gates remain authoritative.

Current warning:

- `policy_backtest_summary.json` can report `policy_too_loose`. While that is
  present, do not promote this layer. Treat it as conservative, paper-only, and
  under review.

Remaining:

- Continue daily `policy_backtest.py --write-summary` until
  `policy_too_loose` clears across multiple paper sessions.
- Add stronger drift thresholds once normal paper-session variance is known.

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
- a demotion path for every promoted state. A `paper_gate` or `warn_only` model
  must move back to `observe_only` when rolling performance, calibration,
  feature drift, regime drift, or fill quality breaches thresholds.

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

Retraining policy:

- Default to manually reviewed batch retraining.
- Initial cadence is review after 20 trading sessions or after a drift or
  performance alert, whichever comes first.
- Retraining triggers include rolling performance decay, feature drift, symbol
  universe drift, macro regime shift, approval/rejection mix drift, and the
  after-close learning review.
- The after-close learning pipeline should feed retraining readiness reports
  first, not silently deploy new models.

### Serving Layer

Goal: service-owned prediction observation used for logging, dashboards, and
conservative downside-only sizing modifiers.

Current state:

- `ml_platform.serving` defines a dormant read-only `PredictionProvider`
  interface and SQLite implementation.
- `prediction_cache.py` is a compatibility wrapper around service/repository
  owned cache loading. It preloads
  `daily_symbol_predictions` into an in-memory dict keyed by symbol, refreshes
  on a 60-second TTL outside webhook handling, and exposes memory-only reads to
  the live signal path.
- `/status` exposes prediction-cache age, symbol count, load duration, and
  stale/error state.
- The existing deterministic `prediction_gate` is documented in code as the
  deterministic signal-quality gate. Cached ML predictions are attached as
  `ml_prediction_*` fields beside the deterministic gate output.
- Weak ML buckets can apply explicit risk-reducing size caps. High buckets are
  advisory. Hard prediction blocking remains behind explicit promotion.
- `prediction_validation_report.py` now prints deterministic-gate versus
  cached-ML agreement/disagreement from `decision_snapshots` when compare
  fields are present.

Remaining:

- Keep additional ML prediction runtime influence off until clean paper-session
  evidence supports promotion. Compare deterministic-vs-ML
  agreement/divergence first.
- Serving must degrade to no prediction if disabled, stale, missing, or failed;
  it must never block signal processing.
- Continue validating the serving latency contract in session logs: target
  25 ms, hard timeout 50 ms, in-memory TTL cache loaded outside the webhook
  path, TTL 60 seconds, and failure behavior is fail-open to no prediction.

### Operator UI/API

Goal: status, prediction explanations, model comparison, daily readiness, and
risk review.

Current state:

- `/status`, `ops_check.py`, Tuesday QA automation, and read-only reports cover
  much of the operator surface.

Remaining:

- Add model comparison and daily ML readiness reports.
- Add model-card status to operator output once real models exist.
- Surface after-close policy artifact health, hash drift, and stale-artifact
  warnings in ops checks.

### Data Retention Layer

Goal: keep the ML/audit trail useful without letting `trades.db` grow without
bound.

Retention tiers:

- Hot: queried in webhook/status paths. Examples: open positions, cooldowns,
  recent sells, latest market context, latest policy artifact hashes.
- Warm: queried by daily ops and evaluation reports. Examples: recent trades,
  feature snapshots, labeled setups, daily context/events/predictions.
- Cold: archival/replay only. Examples: old decision snapshots, historical
  market context snapshots, override history, rejected-signal forward outcomes,
  and old policy artifact versions.

Pending:

- Classify every new ML/audit table as hot, warm, or cold before adding it to
  `trades.db`.
- Decide whether cold archives stay in the main SQLite DB, move to separate
  SQLite files, or become file-based archives.
- Add retention/compaction commands before indefinite snapshot retention is
  enabled.

## Recommended Phases

### Phase 1: Stabilize Foundation

- Keep the completed architecture cleanup locked down with boundary tests.
  `app.py` is a composition root, and live signal orchestration is
  service-owned.
- Keep formal schema/migration management in `db_migrations.py`; do not add
  scattered runtime schema mutation.
- Make local setup reproducible with `pyproject.toml` or
  `requirements-dev.txt`.
- Add sample/synthetic `market_context.json` fixtures for tests.
- Add regression fixtures from known bad cases: suspect quote/excessive spread,
  late entry, sell-to-buy churn, macro cap full, affordability rejection, price
  sanity failure, earnings hard avoid, missing/stale market context, synthetic
  matched exit, and broker fill mismatch.

Status: complete for the live signal path and architecture boundaries. Further
work should be behavior validation or small composition cleanup, not another
large app-owned migration.

### Phase 2: Make ML Loop Real

- Define one canonical training dataset builder.
- Freeze label definitions.
- Store model/evaluation artifacts under `ml_platform/` and `ml/`.
- Convert the existing similarity model into model `v0` with versioned config.
- Add walk-forward validation before any live influence.
- Add rejected-signal outcome tracking with 5/15/30/60 minute, EOD, MFE, and
  MAE forward returns.
- Resolve the counterfactual problem, fixed-horizon label policy, purged
  validation, and point-in-time context before any real training.

Status: scaffolded, not train-ready. Current priority is validating clean-feed
setup health, prediction bucket separation, conviction persistence, and
exit-capture diagnostics across newer paper sessions.

### Phase 3: Platformize Decisions

- Introduce `PredictionProvider`.
- Keep live behavior observe-only.
- Add dashboards/reports comparing current decisions vs prediction-assisted
  decisions.
- Promote only after evidence: observe-only -> warn-only -> soft modifier ->
  guarded paper gate.

Status: provider/cache path is integrated as service-owned prediction
observation. Additional authority remains blocked pending paper evidence.

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
- `strong_day_participation`: post-session full-symbol-universe participation
  outcomes, including symbols that were strong without TradingView alerts;
  used by prediction validation and intelligence prediction reports after
  `strong_day_participation_report.py --write-db` runs.
- `market_intelligence.tape_reader`: future intraday tape labels from bar data.
- `strategy.trade_scorer`: future shadow-only trader-brain score, with leakage
  controls before historical use.
- `decision_context` / `decision_policy`: future policy-replay features, not
  live authority.

## Trend And Momentum Use

Existing order intelligence:

- Service-owned runtime/context builders track trend state from signal history
  and persist trend fields on trade rows.
- Live signal services use short momentum, session momentum, setup observation,
  prediction diagnostics, strategy observation, and buy-opportunity scoring in
  decision context and audit rows.
- `session_momentum.py`, `rolling_momentum.py`, and
  `position_momentum_monitor.py` are thin or service-backed entrypoints feeding
  session/position risk visibility.
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
- Strong-day participation rows are also post-session evaluation evidence.
  They are valid for prediction validation and cohort analysis, but not as
  pre-decision training features unless joined through a leakage-safe label
  builder.

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

## Current Refactor State

Completed:

1. Live signal processing moved out of `app.py`.
2. Context, approval, sizing, execution, audit, startup, route registration,
   runtime state, market-data adapters, and portfolio rotation are
   service-owned.
3. Runtime/report/ops/ML DB access moved behind repositories.
4. Market-data access moved behind approved services/adapters.
5. Temporary architecture allowlists are empty and guarded by tests.

Remaining:

1. Remove compatibility wrappers only after import checks prove they are unused.
2. Keep report/backfill scripts thin and repository-backed.
3. Add new architecture guards before relaxing any boundary.

## Promotion rule

A model can only move from observe-only to paper-trading influence after it has:

- enough feature and label coverage,
- matched-trade outcome coverage,
- stable out-of-sample validation,
- an explicit rollback plan,
- an environment flag defaulting off,
- operator-visible reports showing what it would have changed.

## Best Next Additions

1. Done: add schema/migration management.
2. Done: add immutable decision snapshots.
3. Done: add `feature_available_at`, `feature_generated_at`,
   `feature_age_seconds`, `source`, `is_stale`, and `staleness_reason` fields
   to `feature_snapshots_v2`.
4. Validate serving latency and fail-open behavior during clean paper sessions.
5. Done: add policy-artifact registry, known-good pointer, rollback command,
   after-close failure alert, manifest registry hash/known-good id, and
   `ops_check.py policy-artifacts` coverage for the after-close learning memory
   files. Continue reviewing stale/unexpected hash drift thresholds.
6. Started: add timestamped override history and dataset-manifest override
   hashes. Current point-in-time archive snapshots market context, override
   files, policy artifact hashes, and symbol-universe version.
7. Done: add conviction persistence health and sample diagnostics.
8. Next: use clean-session reports to validate setup errors, fallback health,
   dominant limiter attribution, weak/degraded loss containment, full-exit
   capture ratio, winner-became-loser count, and prediction bucket separation.
9. Started: add data-retention tiers and archive/compaction commands. Current
   policy classifies hot/warm/cold tables and leaves destructive compaction
   disabled.
10. Done: complete `app.py` decomposition for the live signal path.
11. Done: add `rejected_signal_outcomes` schema target plus
   `rejected_signal_outcome_builder.py` and `ops_check.py rejected-outcomes`
   coverage/label-quality reporting. The post-session cron now runs the
   builder daily before validation. Continue collecting multiple paper sessions
   before treating counterfactual labels as training-ready.
12. Done: define label v1 formally with fixed-horizon returns, excursion
    labels, classification labels, and exit-policy requirements.
13. Done: add dataset manifest generation to dataset export flow.
14. Started: staged observe-only ML integration lane and `staged-readiness`
    report.
15. Started: convert the similarity model into versioned model `v0` with
    research-only metadata.
16. Done: build read-only `replay-decisions` v1. It re-runs
    `decision_policy` against stored `decision_snapshots` account-state JSON,
    reports policy drift, joins changed decisions to realized/rejected outcomes,
    estimates friction-adjusted decision deltas, and emits best/worst changed
    decisions without changing live behavior.
17. Add calibration and walk-forward evaluation.
18. Started: define the first retraining-readiness report and 20-session review
    cadence.
19. Done: expose symbol intelligence in `/status`; weak prediction values can
    only reduce risk through explicit size caps.
20. Started: evaluate whether TradingView alerts should remain primary, become
    secondary, or be replaced by an Alpaca-bar-derived internal signal
    generator after side-by-side paper-session evidence. `auto_buy_outcome_report.py`
    now compares internal candidate forward returns against the TradingView
    signal baseline, and `strong_day_participation_report.py --write-db`
    captures full-universe strong-session coverage including no-alert symbols.
21. Done: add post-learning point-in-time archive to
    `run_after_close_learning.sh` after policy artifact registration, so
    after-close strategy/policy memory refreshes are archived as well as
    pre-market context.
22. Done: add `auto_buy_decision_snapshots` so the internal auto-buy execution
    path records candidate decisions, live block reasons, risk cross-check
    reasons, and submitted order metadata outside the main webhook path.
23. Started: route fixed-horizon label generation through
    `label_v1_builder.py`, which validates feature availability/staleness
    audit fields before delegating to the current label feature builder.
24. Started: entry-intelligence instrumentation v1. The live signal path now
    captures momentum acceleration, volume surge ratio, recent-base extension,
    prior-session strong-day context, and fresh tape classification into
    `decision_snapshots`; `feature_snapshots_v3` includes the new signal-time
    training features; `entry_quality_report.py` runs post-session in
    observe-only mode. Do not promote entry-quality hard gates until the report
    has enough matched outcomes per bucket.

Critical blockers before real training:

1. Continue collecting and validating counterfactual outcomes for rejected
   signals across multiple paper sessions. Daily validation must keep rejected
   row coverage complete, separate labeled/partial/pending/error rows, verify
   all 5m/15m/30m/60m/EOD horizons where structurally available, preserve
   action-aware MFE/MAE signs, and mark near-close rows as partial.
2. Continue validating fixed-horizon label v1. Default training exports now use
   complete fixed-horizon rows only, but 60m and action-aware MFE/MAE targets
   still need to be added to the feature-snapshot label schema.
3. Version realized-exit labels by exit logic before any realized-PnL training
   claims. Do not mix trades across changing exit policies without explicit
   `exit_policy_version` and `position_manager_version` controls.
4. Implement purged/embargoed walk-forward validation.
5. Continue point-in-time context archiving before using `strategy.trade_scorer`
   in historical replay; pre-market and post-learning archive commands are
   staged, but replay selection logic is not yet implemented.
6. Continue symbol-universe versioning and review remaining candidates:
   F, HBAN, KEY, KHC, CRM, PDD, HPQ, BBY, DLTR, GPS, AEO, BKE.
7. Sequencing note: `run_after_close_learning.sh` currently runs before
   `run_post_session_review.sh` builds rejected-signal outcomes. That is
   acceptable while after-close learning does not consume rejected outcomes,
   but the order must change before rejected outcomes become a learning input.

The biggest missing concept is auditability of what the bot knew at decision
time. Without that, training, evaluation, and promotion can look sophisticated
while still being structurally unreliable.
