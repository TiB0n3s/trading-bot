# Daily Operations - 2026-06-17 Auto-Buy Lock Contention

## Source
- Primary log: `auto_buy.log`.
- Related lock evidence: `label_features.log` and `session_momentum.log`.
- User-observed failure window: `2026-06-17T19:56:01+00:00` auto-buy run.

## Outcome
- Auto-buy candidate scoring was no longer the bottleneck.
- The failed `19:56 UTC` run built 40 candidates in `6.02s`.
- The run crashed after candidate generation while writing the primary auto-buy audit snapshot.
- SQLite raised `sqlite3.OperationalError: database is locked` from `auto_buy_repo.insert_candidate_and_snapshot`.

## Diagnosis
- This was a write-path lock failure, not a strategy-scoring failure.
- `run_label_features` was active from `19:50 UTC` and logged repeated `database is locked` errors around `19:54-19:56 UTC`.
- `session_momentum` later kept writing `bar_pattern_features` rows after the market-close boundary.
- Auto-buy, label features, session momentum, bot events, and candidate-universe capture all share `trades.db`, so one writer can block best-effort audit writes.

## Fixes Committed
- `d67be6a` - Speed up learned auto-buy tiebreaker.
- `0e2ec30` - Avoid write-path locks in auto-buy reads.
- `f64bfdc` - Fail fast on locked bar pattern reads.
- `b3e7460` - Use symbol index for live bar pattern lookup.
- `7b032e6` - Add auto-buy post-build timing.
- `d1097e3` - Reuse auto-buy audit persistence services.
- `e003007` - Fail open on locked auto-buy audit writes.
- `8230be2` - Bound auto-buy audit write lock waits.

## What Changed
- The slow `JNPR` path was isolated to bar-pattern lookup, not strategy memory.
- Live bar-pattern lookup now uses a symbol-first index and a short read lock budget.
- Candidate-universe and bot-event services are reused during the auto-buy run instead of reinitializing schema/indexes per row.
- Locked primary auto-buy audit snapshot writes now fail open for lock errors.
- Auto-buy best-effort audit writes now use a short lock budget via `AUTO_BUY_AUDIT_WRITE_BUSY_TIMEOUT_MS` instead of waiting behind a long global SQLite busy timeout.

## Validation
- Focused tests passed:
  - `tests/test_auto_buy_manager.py`
  - `tests/test_auto_buy_repo.py`
  - `tests/test_candidate_universe_service.py`
  - `tests/test_bot_events_service.py`
  - `tests/test_db_connection.py`
- Ruff format and lint passed.
- Commit hooks passed on the lock-handling commits.
- No post-`8230be2` in-market auto-buy run appeared before the close boundary, so production validation rolls to the next scheduled market-hours run.

## Lessons
- Separate scoring latency from persistence latency in the logs. `build_candidates` can be healthy while post-build audit writes still fail or timeout.
- Best-effort audit persistence should not have trading-path authority.
- SQLite's default/global busy timeout is too expensive for per-candidate audit writes during write storms.
- Per-row schema/index initialization is risky in hot paths, especially with SQLite.
- Defer-or-skip coordination helps, but long-running writers can still overlap with jobs that only defer at startup.

## Follow-Ups
- [ ] Watch the next market-hours auto-buy run after `8230be2`; expected result is no crash on locked audit writes and no 5-second-per-row audit waits.
- [x] Add a DB workload report or ops check that flags long-running writer overlap with auto-buy windows.
  - Result: `python3 scripts/db_workload_report.py --writer-overlap-date YYYY-MM-DD --writer-overlap-duration-threshold-sec 60` flags long `run_label_features` / `session_momentum` overlaps with `auto_buy_manager`.
- [ ] Consider batching auto-buy audit writes into one transaction when the DB is available.
- [ ] Consider moving best-effort audit/event streams to a separate SQLite database or append-only queue if writer contention persists.
- [ ] Review `run_label_features` and `session_momentum` write batches; they are the current lock-pressure sources.

## Related
- [[auto_buy_manager]]
- [[SQLite lock contention]]
- [[candidate_universe]]
- [[bot_events]]
- [[bar_pattern_features]]
- [[strategy_memory]]
