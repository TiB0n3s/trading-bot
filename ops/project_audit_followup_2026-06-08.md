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
- **Dependency split**: `requirements-base.txt` is the slim runtime subset,
  `requirements-research.txt` adds optional ML/quant dependencies, and
  `requirements.txt` delegates to the full research environment.
- **Architecture surface tracking**: `ops_check.py architecture-surface` now
  measures root/module sprawl, oversized decision files, raw env access, and
  `src/trading_bot` skeleton readiness. `ops/compatibility_deletion_plan.md`
  tracks wrapper/module migration and deletion conditions.

## Current High-Priority Gaps

These remain valid roadmap items before any cash-live promotion:

1. **Database backups and restore drills**
   - Add automated local SQLite backups for `trades.db`, `predictions.db`, and
     `jobs.db`.
   - Add restore verification so backup success is not assumed from file
     existence alone.
2. **Observability and alerting**
   - Add service/job metrics for runtime health, DB lock pressure, broker
     errors, order latency, rejected/approved flow, and model-staleness state.
   - Start with lightweight local metrics/log summaries before committing to a
     full Prometheus/Grafana stack.
3. **Secrets management hardening**
   - `/etc/trading-bot.env` remains the current secret source.
   - Keep secrets out of images, docs, logs, and systemd unit files.
   - Evaluate a secrets manager only after the operational surface stabilizes.
4. **Load and burst testing**
   - Add a local paper-only webhook/load harness that can replay high-volume
     signal bursts without touching the broker.
5. **Incident management**
   - Add a simple incident/postmortem template and link incidents to job-run,
     order, and learning artifacts.
6. **Model validation governance**
   - Existing validation reports are strong, but promotion still needs a
     consolidated gate comparing candidate models against baseline behavior,
     costs, slippage, exits, and regime stability.
7. **Feature flags and kill switches**
   - Many env flags exist, but there is not yet a single feature-flag inventory
     with ownership, default, authority level, rollback action, and audit link.
8. **Architecture surface reduction**
   - The package skeleton and audit metrics exist, but runtime implementations
     still need staged migration out of root files, generic `services/`, and
     oversized decision modules.

## Documentation Rule

When a new operational command, authority path, dependency split, scheduler, or
runtime safety rule is added, update:

- `README.md` for operator-facing status and commands.
- `CLAUDE.md` for agent/collaboration guidance.
- `ops/README.md` or a focused runbook for operational procedures.
- The relevant package README when behavior is local to `ml/`, `ml_platform/`,
  `ops/`, or another package.
