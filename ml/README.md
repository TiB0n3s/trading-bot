# ML Research Platform

This directory is for research scaffolding only. Nothing here should affect live
or paper-trading decisions unless a future promotion process explicitly wires it
in behind tests, logging, environment flags, and rollback.

## Current Rule

ML output starts observe-only. Some governed adapters can now be wired as
paper/live conservative authority only after registry status, staleness, env
flags, tests, and promotion evidence pass. They may block or reduce size where
explicitly allowed; they must not increase size, loosen hard gates, submit
orders, or bypass broker/risk controls.

## Planned Layers

1. Dataset definitions and exports.
2. Experiment configs and metrics.
3. Model artifact/registry conventions.
4. Shadow serving/reporting.
5. Paper-only soft influence after validation.
6. Data governance, replay, and promotion governance.

## Promotion Requirements

Before any model can affect paper trading it must have:

- stable feature and label coverage,
- matched-trade outcome coverage,
- out-of-sample validation,
- calibration review,
- clear explanation/reporting,
- an environment flag defaulting off,
- a rollback plan,
- no ability to loosen hard risk or broker controls.
- a decision-time audit trail proving there was no feature leakage.

## Governance Commands

```bash
python3 -m ml_platform.cli governance-contract
python3 -m ml_platform.cli dataset-manifest --start-date 2026-05-20 --end-date 2026-05-26
python3 -m ml_platform.cli model-card-template --model-id similarity_v0
python3 -m ml_platform.cli replay-decisions --start-date 2026-05-01 --end-date 2026-05-26 --candidate-model similarity_v0
python3 -m ml_platform.cli staged-readiness --start-date 2026-05-26 --end-date 2026-05-26 --candidate-model similarity_v0 --prediction-symbol AAPL
python3 -m ml_platform.cli retraining-readiness --start-date 2026-05-26 --end-date 2026-05-26 --trading-sessions-observed 0
python3 -m ml_platform.cli env-policy
```

These commands are research scaffolds. They do not write to `trades.db`, call a
broker, or affect the current paper-trading runtime.

## Current Scaffolding

```bash
python3 -m ml_platform.cli profile-dataset --start-date 2026-05-20 --end-date 2026-05-26
python3 -m ml_platform.cli export-brain-features --date 2026-05-26 --output /tmp/brain_features.csv
python3 -m ml_platform.cli create-experiment setup_baseline --dataset-start 2026-05-20 --dataset-end 2026-05-26
python3 -m ml_platform.cli integration-contract
python3 -m ml_platform.cli list-models
python3 ai_dependency_status.py
python3 train_supervised_predictions.py --limit 5000 --artifact-output ml/models/supervised_entry_v1/model.joblib
python3 train_regime_model.py --limit 1000 --artifact-output ml/models/regime_hmm_v1/model.joblib
python3 score_financial_sentiment.py --text "Example headline text"
python3 run_staged_tests.py
```

Generated experiment/model artifacts are local research outputs and are ignored
by default. Promote only reviewed metadata/artifacts intentionally.

Fresh research installs should install the runtime requirements first, then the
research overlay:

```bash
pip install -r requirements.txt
pip install -r requirements-research.txt
```

The research overlay includes the optional packages used by checked-in commands:

- DuckDB and PyArrow for Parquet/research exports.
- scikit-learn and joblib for supervised entry-prediction artifacts.
- hmmlearn for HMM regime artifacts.
- XGBoost for supervised asymmetric candidate models.
- torch for governed Transformer authority candidates.

These packages are research infrastructure only. Installing them does not grant
model output any live authority.

`models/similarity_v0/` is the first versioned research placeholder. It contains
metadata only: no trained model artifact, no runtime import, and no permission
to influence orders, position sizing, or risk controls.

`models/supervised_entry_v1/` is the intended local path for supervised entry
prediction experiments from `train_supervised_predictions.py`. The smoke-tested
implementation uses sklearn RandomForest when dependencies and training rows are
available.

`models/regime_hmm_v1/` is the intended local path for HMM regime experiments
from `train_regime_model.py`. HMM convergence warnings should be treated as
research evidence to review, not as a runtime failure or promotion signal.

The optional sentiment command can use FinBERT when the transformer dependency
is installed, but sentiment output remains supporting evidence only.

Container targets preserve the same boundary: `tradingbot-runtime` excludes the
heavy ML/research stack and must pass fallback-focused tests; `tradingbot-research`
includes the optional quant/ML packages for training, validation, and diagnostics.
`pyproject.toml` mirrors the research dependency group and also declares optional
`dashboard`, `timescale`, and `sentiment` extras for intentionally optional
Streamlit, asyncpg, and transformer integrations.
