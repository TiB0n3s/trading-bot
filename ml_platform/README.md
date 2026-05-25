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
python3 -m ml_platform.cli governance-contract
python3 -m ml_platform.cli dataset-manifest --start-date 2026-05-20 --end-date 2026-05-26
python3 -m ml_platform.cli label-taxonomy
python3 -m ml_platform.cli model-card-template --model-id similarity_v0
python3 -m ml_platform.cli replay-decisions --start-date 2026-05-01 --end-date 2026-05-26 --candidate-model similarity_v0
python3 -m ml_platform.cli env-policy
python3 -m ml_platform.cli get-prediction --date 2026-05-26 --symbol AAPL
python3 -m ml_platform.cli list-models
```

## Boundaries

- No model serving.
- `serving.py` is an interface scaffold only; it is not imported by runtime.
- No runtime decision changes.
- No writes to `trades.db`.
- No broker/order calls.
- Registry status defaults to `research`.
- ML kill switches default off.

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
- non-authority language for every model card.

The first hard rule is auditability: future training rows must record what was
knowable at decision time before they can be trusted for evaluation or
promotion.

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
