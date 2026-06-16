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

## Research Reports

- `historical_market_view.py` audits existing historical
  `bar_pattern_features` coverage, summarizes baseline outcomes by
  symbol/regime/pattern/time buckets, optionally exports a flat CSV research
  substrate, and runs the corrected blocked/family-wise feature scan over
  historical candle rows. It is read-only and cannot affect live or paper
  trading authority.
