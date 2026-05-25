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

## Current Scaffolding

```bash
python3 -m ml_platform.cli profile-dataset --start-date 2026-05-20 --end-date 2026-05-26
python3 -m ml_platform.cli create-experiment setup_baseline --dataset-start 2026-05-20 --dataset-end 2026-05-26
python3 -m ml_platform.cli list-models
```

Generated experiment/model artifacts are local research outputs and are ignored
by default. Promote only reviewed metadata/artifacts intentionally.
