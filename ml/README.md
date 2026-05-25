# ML Research Platform

This directory is for research scaffolding only. Nothing here should affect live
or paper-trading decisions unless a future promotion process explicitly wires it
in behind tests, logging, environment flags, and rollback.

## Current Rule

ML output is observe-only.

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
broker, or affect Tuesday's paper-trading runtime.

## Current Scaffolding

```bash
python3 -m ml_platform.cli profile-dataset --start-date 2026-05-20 --end-date 2026-05-26
python3 -m ml_platform.cli export-brain-features --date 2026-05-26 --output /tmp/brain_features.csv
python3 -m ml_platform.cli create-experiment setup_baseline --dataset-start 2026-05-20 --dataset-end 2026-05-26
python3 -m ml_platform.cli integration-contract
python3 -m ml_platform.cli list-models
python3 run_staged_tests.py
```

Generated experiment/model artifacts are local research outputs and are ignored
by default. Promote only reviewed metadata/artifacts intentionally.

`models/similarity_v0/` is the first versioned research placeholder. It contains
metadata only: no trained model artifact, no runtime import, and no permission
to influence orders, position sizing, or risk controls.
