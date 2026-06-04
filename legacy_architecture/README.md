# Legacy Architecture

This directory documents architecture that has been retired from the live
decision-making environment.

Do not schedule or call legacy flows from cron, `job_runner.py`, `app.py`,
`auto_buy_manager.py`, `position_manager.py`, or the live signal path. Legacy
items may remain as historical references or manual recovery notes only.

## After-Close Shell-Owned Learning Sequence

Legacy status: retired on 2026-06-04.

The previous `run_after_close_learning.sh` wrapper directly executed a sequence
of learning and report scripts before and after invoking
`pipeline/after_close_learning.py`, including:

- `trade_matcher.py`
- `strategy_learner.py`
- `excursion_report.py --write-memory`
- `missed_opportunity_report.py --write-memory`
- `symbol_momentum_timing_report.py --write-memory`
- `policy_backtest.py --write-summary`
- `portfolio_replacement_report.py --write-memory`
- `strategy_brain_report.py`
- `policy_artifacts.py register`
- `archive_context_state.py`

That shell-owned sequence has been replaced by
`pipeline/after_close_learning.py`, which is now the single owner of recurring
after-close learning, report-memory refresh, policy artifact registration, and
point-in-time archival.

The individual scripts are still active manual/operator tools where useful, but
their scheduled after-close impact must flow through the pipeline.

## Manual-Only Root Utilities

Legacy status: manual/operator tools only.

The following root scripts are not part of cron, `job_runner.py`, Flask startup,
auto-buy, position management, or the live signal path. Keep them out of live
decision wiring unless they are promoted through a service/pipeline boundary and
covered by tests.

- `add_symbol_event.py`
- `backfill_setup_labels.py`
- `init_prediction_db.py`
- `parse_market_brief.py`
- `replay_report.py`
- `score_symbol_event.py`
- `signal_event_builder.py`

Notes:

- `wsgi.py` is not listed here even though static repo references are sparse;
  it is a deployment entrypoint and should remain at the root.
- Manual tools may be moved under `ops/manual_tools/` in a future cleanup pass,
  but only after documentation and operator command references are updated.
