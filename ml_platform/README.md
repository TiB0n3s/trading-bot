# ML Platform Package

This package contains offline/research scaffolding only. It is intentionally not
imported by `app.py`, `broker.py`, cron, or order execution.

## Commands

```bash
python3 -m ml_platform.cli profile-dataset --start-date 2026-05-20 --end-date 2026-05-26
python3 -m ml_platform.cli create-experiment setup_baseline --dataset-start 2026-05-20 --dataset-end 2026-05-26
python3 -m ml_platform.cli list-models
```

## Boundaries

- No model serving.
- No runtime decision changes.
- No writes to `trades.db`.
- No broker/order calls.
- Registry status defaults to `research`.

Promotion beyond research requires explicit operator approval, tests, reports,
environment flags defaulting off, and rollback.
