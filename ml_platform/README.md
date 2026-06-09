# ML Platform Package

This package contains offline/research scaffolding only. It is intentionally not
imported by `app.py`, `broker.py`, cron, or order execution.

## Commands

```bash
python3 -m ml_platform.cli profile-dataset --start-date 2026-05-20 --end-date 2026-05-26
python3 -m ml_platform.cli export-brain-features --date 2026-05-26 --output /tmp/brain_features.csv
python3 -m ml_platform.cli create-experiment setup_baseline --dataset-start 2026-05-20 --dataset-end 2026-05-26
python3 -m ml_platform.cli integration-contract
python3 -m ml_platform.cli evaluation-plan
python3 -m ml_platform.cli retraining-readiness --start-date 2026-05-26 --end-date 2026-05-26 --trading-sessions-observed 0
python3 -m ml_platform.cli governance-contract
python3 -m ml_platform.cli dataset-manifest --start-date 2026-05-20 --end-date 2026-05-26
python3 -m ml_platform.cli label-taxonomy
python3 -m ml_platform.cli lifecycle-contract
python3 -m ml_platform.cli feature-registry
python3 -m ml_platform.cli label-hierarchy
python3 -m ml_platform.cli serving-contract
python3 -m ml_platform.cli promotion-metrics --start-date 2024-06-01 --end-date 2026-06-04
python3 -m ml_platform.cli model-card-template --model-id similarity_v0
python3 -m ml_platform.cli replay-decisions --start-date 2026-05-01 --end-date 2026-05-26 --candidate-model similarity_v0 --friction-bps 10
python3 -m ml_platform.cli staged-readiness --start-date 2026-05-26 --end-date 2026-05-26 --candidate-model similarity_v0 --prediction-symbol AAPL
python3 -m ml_platform.cli env-policy
python3 -m ml_platform.cli get-prediction --date 2026-05-26 --symbol AAPL
python3 -m ml_platform.cli list-models
```

## Boundaries

- No direct model serving from this package into order execution.
- `serving.py` is a read-only provider scaffold only; it is not imported by runtime.
- `staged.py` composes ahead-of-live integration evidence only; it is not imported by runtime.
- `replay.py` is read-only. It joins changed replay decisions to
  `matched_trades` and `rejected_signal_outcomes` when available, then reports
  avoided losers, missed winners, recovered missed winners, introduced losers,
  friction-adjusted simulated delta, and best/worst changed decisions.
- No runtime decision changes unless a separately tested policy/authority
  adapter is enabled by explicit env flags, registry status, staleness checks,
  and promotion evidence.
- No writes to `trades.db`.
- No broker/order calls.
- Registry status defaults to `research`.
- ML kill switches default off.
- Root-level AI analytics/training CLIs may write local research artifacts or
  optional Timescale smoke-test rows, but they do not place orders or change
  live signal authority.
- Governed Transformer authority is available only through the explicit
  registry/env/staleness-checked adapter. When enabled and promoted, it can
  block or reduce size only; it cannot approve, increase size, or submit orders.
- Historical-bar trend-scan/triple-barrier candidates and asymmetric supervised
  candidates are validation inputs until promotion evidence and authority
  configuration explicitly allow a conservative paper/live role.
- The mandatory ML lifecycle is:
  dataset build, manifest, feature parity validation, purged walk-forward
  validation, calibration report, replay decision delta, cost/slippage report,
  promotion assessment, registry write, shadow serving, monitored paper
  authority, and rollback/demotion. Chronological 80/20 validation is allowed
  only as observe-only research evidence.

Promotion beyond research requires explicit operator approval, tests, reports,
environment flags defaulting off, and rollback.

## Governance

`governance.py` is the contract layer for the ML platform. It defines:

- leakage checkpoints and feature availability requirements,
- immutable decision snapshot fields,
- dataset manifest identity fields,
- label taxonomy v1,
- order/fill truth hierarchy and fill confidence,
- model abstention output,
- minimum sample gates,
- baseline comparisons,
- friction/slippage assumptions,
- calibration and drift checks,
- counterfactual and selection-bias policy,
- point-in-time context requirements,
- purged/embargoed validation requirements,
- class-imbalance metrics,
- serving latency and fail-open behavior,
- demotion and retraining policy,
- non-authority language for every model card.

The first hard rule is auditability: future training rows must record what was
knowable at decision time before they can be trusted for evaluation or
promotion.

The second hard rule is counterfactual coverage: a model trained only on
approved trades is selection-biased and cannot claim to know which rejected
signals were worth taking.

Runtime prediction integration must use `prediction_cache.py`: target 25 ms,
hard timeout 50 ms, in-memory TTL cache loaded outside the webhook path, and
fail-open to no prediction. Provider failure must never block signal
processing. `daily_symbol_predictions` values are compare-only beside the
deterministic signal-quality gate until validation says otherwise.

## Lifecycle Contract

`lifecycle.py` defines the non-negotiable promotion path for every ML surface.
Model training can still write observe-only artifacts, but candidate
registration and stronger authority require evidence for all lifecycle stages:

- dataset manifest and point-in-time feature provenance,
- runtime/offline feature parity,
- purged and embargoed walk-forward validation,
- calibration and Brier evidence,
- replay against actual bot decisions and rejected opportunities,
- slippage/cost/exit-adjusted trading metrics,
- promotion assessment and registry metadata,
- shadow serving with provider/cache/latency/staleness audit,
- monitored paper authority,
- rollback and demotion controls.

Required promotion metrics include expected value, false-positive cost,
false-negative opportunity cost, avoid-loser precision/recall, Brier score,
calibration error, profit factor, max drawdown, MFE/MAE delta,
slippage-adjusted decision delta, capture ratio, and stability by regime,
symbol, and time of day.

`promotion-metrics` computes those values from lifecycle analysis rows plus
read-only replay. It intentionally separates metric completeness from authority:
complete metrics can support candidate registration evidence, but monitored
paper authority additionally requires positive expected value, profit factor
above threshold, acceptable calibration/Brier values, and measured stability. If
that authority assessment fails, ML may still reduce size, block weak setups, or
annotate context. In paper/dry-run, the separate bounded exploration authority
can approve or increase size when current deterministic evidence is strong
enough and the configured caps allow it. Cash modes remain excluded.

Paper exploration authority is configured through:

- `PAPER_EXPLORATION_AUTHORITY_ENABLED`
- `PAPER_EXPLORATION_MIN_SETUP_SCORE`
- `PAPER_EXPLORATION_MIN_BUY_OPPORTUNITY_SCORE`
- `PAPER_EXPLORATION_MIN_PREDICTION_SCORE`
- `PAPER_EXPLORATION_SIZE_LIFT_MULTIPLIER`
- `PAPER_EXPLORATION_MAX_POSITION_SIZE_PCT`

`services.model_validation_governance_service` and
`ml_platform.promotion` reject simple split validation for candidate
registration/promotion. This keeps 80/20 training scores useful for diagnostics
without letting them become authority.

## Feature And Label Contracts

Runtime and offline ML features should resolve through the versioned registry
under `src/trading_bot/learning/features/`. The current registry includes:

- `decision_features_v4`
- `bar_pattern_features_v1`
- `advanced_alpha_features_v1`

Each feature has explicit null semantics, point-in-time rules, authority
eligibility, and semantic version metadata. Dataset builders, replay services,
and serving adapters should consume these definitions instead of recreating
feature lists locally.

`src/trading_bot/learning/labels.py` defines authority caps for label families.
Realized trade and matched lifecycle labels can eventually support narrow
paper/live risk-reduction roles after the full lifecycle. Rejected-signal,
triple-barrier, trend-scan, diagnostic, and regime labels remain observe-only or
paper-review inputs until they have replay evidence and confounder controls.

Transformer/torch outputs are governed the same way. They may be wired as a
full authority provider only after temporal sequences, feature parity, replay,
shadow serving, and monitored paper authority evidence exist. A seq_len=1
transformer is not sufficient promotion evidence by itself.

## Serving Contract

`serving.py` exposes a fail-open, cache-aware prediction provider contract. The
runtime contract requires:

- provider identity and model id/version audit fields,
- in-memory TTL cache outside the webhook path,
- timeout/failure behavior that returns no prediction,
- stale prediction detection,
- numeric output clipping before runtime context,
- shadow-serving support before any paper authority.

Provider failure must reduce ML influence to neutral state. It must not block
signal processing, broker safeguards, or deterministic risk gates.

## Existing Policy Artifacts

The after-close learning pipeline already writes memory files that influence
runtime decisions:

- `strategy_memory.json`
- `portfolio_replacement_memory.json`
- `excursion_memory.json`
- `missed_opportunity_memory.json`
- `policy_backtest_summary.json`

These are governed as `policy_artifact` inputs. Their hashes are included in
dataset manifests, and `/status` exposes their current hashes/mtimes,
generated timestamps, registry state, and known-good pointer under
`policy_artifacts`.

Policy artifact writes use atomic temp-file replacement, and
`POLICY_ARTIFACTS_ENABLED=false` makes live loaders return neutral state without
deleting the artifact files.

```bash
python3 policy_artifacts.py register --label manual_review --source operator --known-good
python3 policy_artifacts.py rollback --dry-run
```

## Brain Integration

`brain_features.py` turns existing deterministic bot intelligence into ML
features:

- `setup_engine.classify_setup`
- `daily_symbol_context`
- `daily_symbol_events`
- `daily_symbol_predictions`
- snapshot trend/momentum fields from `feature_snapshots`

This is the first bridge between the current bot brain and the future ML
platform. It creates offline features only. It does not import runtime order
code, write to SQLite, or modify decisions.

`feature_parity_contract.py` is the first enforced runtime/offline feature
contract. It verifies that ML-facing decision features have the same names in
`decision_snapshots` and the canonical dataset export, and that each field has
documented null/default semantics and point-in-time cutoff rules.

`canonical_intelligence_v1` is persisted on each decision snapshot as
`canonical_intelligence_json` plus a stable hash/version. It consolidates
regime, momentum, trend, event/intelligence, prediction, setup, strategy,
opportunity, policy-artifact, freshness, confidence, and source timestamp state
for replay and later dataset exports.

`decision_snapshot_features_v4` adds compact `analytics_state` to canonical
intelligence. That state is built from the AI analytics toolkit services:
technical feature engineering, analytics method summaries, portfolio/risk
toolkit context, optional dependency status, sentiment scoring availability,
async-pipeline architecture notes, regime-risk protocol status, dashboard
alerts, and persistent lockout visibility. It is an audit/research feature
surface, not a trading authority.

## Research Training Surfaces

The current root-level training and scoring commands are:

```bash
python3 ai_dependency_status.py
python3 train_supervised_predictions.py --limit 5000 --artifact-output ml/models/supervised_entry_v1/model.joblib
python3 train_regime_model.py --limit 1000 --artifact-output ml/models/regime_hmm_v1/model.joblib
python3 score_financial_sentiment.py --text "Example headline text"
python3 score_financial_sentiment.py --text "Example headline text" --finbert
python3 risk_lockout.py status
```

`train_supervised_predictions.py` can create a sklearn RandomForest artifact and
metadata JSON for offline entry prediction experiments. `train_regime_model.py`
can create a hmmlearn GaussianHMM artifact and metadata JSON for regime
research. Both artifacts remain observe-only unless an explicit future
promotion process adds validation, model-card review, default-off env flags,
runtime tests, and rollback.

The root `requirements.txt` delegates to `requirements-base.txt`, the runtime
dependency set. `requirements-research.txt` is an overlay-only file for optional
research dependencies needed by these checked-in workflows: `duckdb`, `pyarrow`,
`scikit-learn`, `joblib`, `xgboost`, `torch`, and `hmmlearn`. Install runtime
first, then apply the research overlay for reproducible exports/training/tests.
They are installed for reproducible research, not for live authority. The
`runtime` container target uses only `requirements-base.txt`, so
optional-dependency fallback behavior must be validated separately from
research-image training behavior.

`score_financial_sentiment.py` separates the lightweight lexicon fallback from
the optional FinBERT transformer path. Use it to generate sentiment evidence,
not to directly approve, reject, size, or exit trades.

## Staged Readiness

`staged.py` composes the current observe-only platform pieces into a single
readiness report:

- dataset profile,
- dataset manifest,
- brain feature manifest,
- replay output contract,
- prediction-provider contract,
- retraining-readiness blockers,
- promotion gates.

The report must keep `runtime_effect: none`.

`readiness.py` defines the manual retraining-readiness report. It defaults to
`promotion_allowed: false` and lists blockers such as missing feature snapshots,
labels, matched outcomes, and fewer than 20 observed trading sessions.

Use `python3 run_staged_tests.py` to test these ahead-of-live contracts without
changing current live/paper behavior.
