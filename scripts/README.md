# Scripts

Legacy root Python modules live here during the staged package migration.

The repository root intentionally keeps only a small set of compatibility
entrypoints:

- `app.py`
- `wsgi.py`
- `ops_check.py`
- `run_safety_checks.py`

Root entrypoints, safety checks, cron templates, and shell wrappers explicitly
add this directory to `PYTHONPATH`/`sys.path` while runtime and library code
continues moving into `src/trading_bot/`.
