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
- **External observability readiness**:
  `ops_check.py external-observability-readiness` checks metric, alert, and
  dashboard metadata without making network calls. See
  `ops/external_observability_runbook.md`.
- **Secrets manager readiness**: `ops_check.py secrets-manager-readiness`
  checks external provider metadata without reading secrets or making network
  calls. See `ops/secrets_manager_runbook.md`.
- **Paper replay/load probe**: `ops_check.py paper-replay-load-probe` exercises
  webhook routing plus temporary SQLite signal/fill writes without broker
  orders.
- **Explicit high-authority flag metadata**: `ops/feature_flags.yml` documents
  owner, default, authority level, rollback action, and approval rule for
  high-authority cash-live flags.
- **Phase 2 web-runtime extraction**: `src/trading_bot/web/app_factory.py` now
  owns Flask app construction and route registration mechanics. Root `app.py`
  remains the deployed runtime compatibility context while runtime callbacks and
  global exports are migrated in later cleanup slices. `src/trading_bot/runtime/startup.py`
  now owns startup-service wiring, and `src/trading_bot/config/runtime.py` owns
  app-specific runtime settings parsing.

## Current High-Priority Gaps

These remain valid roadmap items before any cash-live promotion:

1. **External observability and alerting**
   - Readiness metadata and runbook now exist.
   - Remaining external action: configure the actual collector/alert/dashboard
     endpoints outside the repo.
2. **External secrets manager evaluation**
   - Provider readiness metadata and runbook now exist.
   - Remaining external action: choose/configure the provider and validate
     retrieval in dry-run.
3. **Load and burst testing**
   - Local diagnostic webhook bursts are available through
     `ops_check.py local-load-probe`.
   - Temporary-DB replay/fill callback coverage is available through
     `ops_check.py paper-replay-load-probe`.
   - Remaining gap: full-day replay with realistic market-data cadence.
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
   - High-authority flag metadata exists in `ops/feature_flags.yml`.
   - Remaining external action: maintain change-approval history when flags are
     changed for cash-live testing.
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
