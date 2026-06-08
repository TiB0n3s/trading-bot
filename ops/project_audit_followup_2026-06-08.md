# Project Audit Follow-Up - 2026-06-08

This note reconciles the external `PROJECT_AUDIT_REPORT.md`,
`MISSING_TOOLS_AND_CONSIDERATIONS.md`, and
`QUICK_REFERENCE_MISSING_TOOLS.md` with the current repository state.

## Superseded Findings

The external audit correctly identified several operational gaps, but some
items have since been implemented:

- **CI/CD**: `.github/workflows/ci.yml` runs compile checks and the fast safety
  harness on pushes to `main` and pull requests.
- **Local commit guardrails**: `.pre-commit-config.yaml` runs Ruff on staged
  Python files and `run_safety_checks.py` before commits.
- **Core tests**: the `tests/` tree is populated. The fast safety harness covers
  risk core behavior, slippage-adjusted Kelly sizing, supervised training,
  Transformer authority, decision-policy authority boundaries, approval/sizing
  services, volume-clock VPIN, volatile-session intelligence, config audit,
  dependency packaging, optional dependency fallbacks, and architecture
  boundaries.
- **Config visibility**: `ops_check.py config-audit` validates typed config
  factories, inventories raw env access, and flags unsafe runtime defaults.
- **Database backups**: `pipeline/database_backup.py` backs up operational
  SQLite files with the SQLite online backup API, writes manifests under
  `backups/databases/`, and verifies copied files with `PRAGMA integrity_check`.
  `ops_check.py database-backups` reports freshness and manifest health.
- **Lightweight observability**: `ops_check.py observability-health` rolls up
  job-ledger cleanliness, backup freshness, service watchdog warnings, and ML
  staleness-guard state without posting external alerts.
- **Local secrets hygiene**: `ops_check.py secrets-hygiene` checks
  `/etc/trading-bot.env` permissions, repo-local env-file candidates,
  `.gitignore` coverage, and Dockerfile leakage risk without printing secret
  values.
- **Dependency split**: `requirements.txt` delegates to the slim runtime
  `requirements-base.txt`; `requirements-research.txt` adds optional ML/quant
  dependencies for explicit research installs. `pyproject.toml` uses normal
  `src/` package discovery, so package imports should use `trading_bot.*`.
- **Architecture surface tracking**: `ops_check.py architecture-surface` now
  measures root/module sprawl, oversized decision files, raw env access, and
  `src/trading_bot` skeleton readiness. `ops/compatibility_deletion_plan.md`
  tracks wrapper/module migration and deletion conditions.
- **Local load diagnostics**: `ops_check.py local-load-probe` exercises the
  Flask webhook route, auth, payload parser, event-record callback, and
  signal-submit callback under bounded local bursts. It is diagnostic-only and
  cannot submit broker orders or mutate trading state.
- **Incident workflow**: `ops_check.py incident-workflow --title "..."` renders
  a structured postmortem template, and `--create` writes an overwrite-safe
  record under `ops/incidents/`.
- **Feature-flag inventory**: `ops_check.py feature-flags` derives a
  diagnostic owner/authority/rollback view from static env-var references.
- **Model validation governance**: `ops_check.py model-governance` consolidates
  candidate diagnostics, observe-only runtime-effect checks, basic quality
  thresholds, and registry live-status blockers without promoting models.
- **Phase 2 web-runtime extraction**: `src/trading_bot/web/app_factory.py` now
  owns Flask app construction and route registration mechanics. Root `app.py`
  remains the deployed runtime compatibility context while runtime callbacks and
  global exports are migrated in later cleanup slices. `src/trading_bot/runtime/startup.py`
  now owns startup-service wiring, and `src/trading_bot/config/runtime.py` owns
  app-specific runtime settings parsing.

## Current High-Priority Gaps

These remain valid roadmap items before any cash-live promotion:

1. **External observability and alerting**
   - Lightweight local observability exists; the remaining gap is external
     metrics/alert publishing for runtime health, DB lock pressure, broker
     errors, order latency, rejected/approved flow, and model-staleness state.
   - Promote to Prometheus/Grafana or another external stack only after the
     local rollup proves the right signals.
2. **External secrets manager evaluation**
   - `/etc/trading-bot.env` remains the current secret source and is covered by
     local hygiene checks.
   - Evaluate a secrets manager only after the operational surface stabilizes.
3. **Load and burst testing**
   - Local diagnostic webhook bursts are available through
     `ops_check.py local-load-probe`.
   - Remaining gap: broader end-to-end paper-session replay with realistic
     market-data cadence, DB-write pressure, and order/fill callbacks.
4. **Incident management**
   - Local incident templates and records exist.
   - Remaining gap: external alert escalation and a required review process for
     cash-live incidents.
5. **Model validation governance**
   - A consolidated diagnostic governance report exists.
   - Remaining gap: promotion-grade comparison against baseline behavior,
     costs, slippage, exits, and regime stability across the required live
     observation window.
6. **Feature flags and kill switches**
   - Local feature-flag inventory exists with inferred ownership, authority
     level, and rollback action.
   - Remaining gap: explicit human ownership/default metadata for every
     cash-live flag and external change-approval history.
7. **Architecture surface reduction**
   - The package skeleton and audit metrics exist, but runtime implementations
     still need staged migration out of root files, generic `services/`, and
     oversized decision modules.
   - Current Phase 2 status: app factory and route registration moved into
     `src/trading_bot/web/app_factory.py`, and startup-service wiring moved
     into `src/trading_bot/runtime/startup.py`; app-specific runtime settings
     parsing moved into `src/trading_bot/config/runtime.py`; remaining work is
     root `app.py` shim reduction, runtime callback extraction, and packaged
     Gunicorn/systemd entrypoint validation.

## Documentation Rule

When a new operational command, authority path, dependency split, scheduler, or
runtime safety rule is added, update:

- `README.md` for operator-facing status and commands.
- `CLAUDE.md` for agent/collaboration guidance.
- `ops/README.md` or a focused runbook for operational procedures.
- The relevant package README when behavior is local to `ml/`, `ml_platform/`,
  `ops/`, or another package.
