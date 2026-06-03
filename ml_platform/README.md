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
python3 -m ml_platform.cli model-card-template --model-id similarity_v0
python3 -m ml_platform.cli replay-decisions --start-date 2026-05-01 --end-date 2026-05-26 --candidate-model similarity_v0 --friction-bps 10
python3 -m ml_platform.cli staged-readiness --start-date 2026-05-26 --end-date 2026-05-26 --candidate-model similarity_v0 --prediction-symbol AAPL
python3 -m ml_platform.cli env-policy
python3 -m ml_platform.cli get-prediction --date 2026-05-26 --symbol AAPL
python3 -m ml_platform.cli list-models
```

## Boundaries

- No model serving.
- `serving.py` is a read-only provider scaffold only; it is not imported by runtime.
- `staged.py` composes ahead-of-live integration evidence only; it is not imported by runtime.
- `replay.py` is read-only. It joins changed replay decisions to
  `matched_trades` and `rejected_signal_outcomes` when available, then reports
  avoided losers, missed winners, recovered missed winners, introduced losers,
  friction-adjusted simulated delta, and best/worst changed decisions.
- No runtime decision changes.
- No writes to `trades.db`.
- No broker/order calls.
- Registry status defaults to `research`.
- ML kill switches default off.
- Root-level AI analytics/training CLIs may write local research artifacts or
  optional Timescale smoke-test rows, but they do not place orders or change
  live signal authority.

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

The root `requirements.txt` includes the optional research dependencies needed
for these checked-in workflows: `duckdb`, `pyarrow`, `scikit-learn`, `joblib`,
and `hmmlearn`. They are installed for reproducible exports/training/tests, not
for live authority.

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
