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

Promotion beyond research requires explicit operator approval, tests, reports,
environment flags defaulting off, and rollback.

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
