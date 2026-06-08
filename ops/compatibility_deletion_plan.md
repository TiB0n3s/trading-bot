# Compatibility Deletion Plan

Runtime-impacting modules should move behind bounded-context packages in small
steps. Root-level files remain compatibility wrappers only after their
implementation moves. Delete wrappers only after callers, cron, systemd,
reports, and tests are updated.

## Rules

- Do not move runtime decision code during an active market session.
- Characterize behavior with tests before splitting a decision surface.
- Root wrappers should contain only imports and `main()` delegation.
- No new `os.getenv` outside `config/` or future `src/trading_bot/config/`.
- Deletion requires a passing `run_safety_checks.py` plus a smoke test for the
  migrated command.

## Initial Targets

| Wrapper/module | Current callers | Replacement | Deletion condition | Target |
| --- | --- | --- | --- | --- |
| `app.py` | Gunicorn/systemd, tests, imports of `process_signal` | `src/trading_bot/web/app_factory.py` plus temporary root shim | Root file below 100 lines, routes/startup/container moved, `/status` and webhook smoke tests pass | Phase 2 |
| `wsgi.py` | Gunicorn | Imports app from `trading_bot.web.app_factory` | Gunicorn config points at package app or stable shim | Phase 2 |
| `ops_check.py` | Operator CLI, cron, docs | `src/trading_bot/ops_checks/cli.py` command registry | Root file below 100 lines, command registry covers existing commands, docs updated | Phase 3 |
| `auto_buy_manager.py` | Cron/operator CLI | `src/trading_bot/signals/auto_buy/cli.py` | Candidate scoring/execution split, paper smoke test passes, cron updated | Phase 4 |
| `position_manager.py` | Cron/operator CLI | `src/trading_bot/positions/cli.py` | Exit evaluation/broker actions/rendering split, paper no-position smoke test passes | Phase 4 |
| `position_momentum_monitor.py` | Cron/operator CLI | `src/trading_bot/positions/momentum_cli.py` | Session momentum/bar capture ownership clarified, cron updated | Phase 4 |
| Root `*_report.py` wrappers | Operator commands, legacy docs | `src/trading_bot/reporting/reports/` or existing `reports/` registry | Registry owns invocation, no direct cron/doc references remain | Phase 3 |
| `services/approval_service.py` | Live signal processor/tests | `src/trading_bot/signals/approval/` package | Gate families split with no authority deltas in characterization tests | Phase 4 |
| `services/context_builder.py` | Live signal processor/tests | `src/trading_bot/signals/context/` package | Context hydration split by domain and snapshot tests pass | Phase 4 |
| `repositories/ops_check_repo.py` | Ops checks/read models | `src/trading_bot/persistence/read_models/` | Query groups split by report category and ops-check smoke tests pass | Phase 5 |

## Phase Checklist

### Phase 1: Skeleton And Metrics

- Add `src/trading_bot/` bounded-context skeleton.
- Add `ops_check.py architecture-surface` to measure root/service/repository
  counts and large decision surfaces.
- Keep all behavior unchanged.

### Phase 2: Web Runtime

- Move Flask factory, routes, auth, response helpers, startup, and container
  wiring into `src/trading_bot/web/` and `src/trading_bot/runtime/`.
- Keep root `app.py` as compatibility shim.
- Lower `app.py` architecture threshold after migration.

### Phase 3: Operator CLI And Reports

- Replace the procedural `ops_check.py` router with a command registry.
- Move report command ownership into grouped report/ops-check packages.
- Remove subprocess/report wrapper duplication where registry invocation exists.

### Phase 4: Runtime Decision Surfaces

- Split `auto_buy_manager.py`, `position_manager.py`, and
  `services/approval_service.py` only after characterization tests are in
  place.
- Preserve paper/cash authority boundaries.

### Phase 5: Persistence Read Models

- Split omnibus reporting repositories into category-specific read models.
- Keep DB write ownership per file explicit.

## Current Targets

| Area | Current target |
| --- | ---: |
| Root Python files | 0-5 |
| Direct `services/` modules | 25-45 |
| `services/ops_checks/` modules | 10-20 |
| `repositories/` modules | 15-30 |
| Root `app.py` | under 100 lines |
| Root `ops_check.py` | under 100 lines |
