# Module Ownership

This file defines the operational boundary for each major runtime surface.

| Surface | Owner Modules | Runtime Authority | Must Not Do |
| --- | --- | --- | --- |
| API / request handling | `api/webhook_routes.py`, `api/status_routes.py`, `api/debug_routes.py`, `api/request_services.py` | Validate HTTP requests, parse payloads, format responses, enqueue work. | Import broker clients, perform SQL, or decide trading policy. |
| Composition | `services/container.py`, `app.py`, `src/trading_bot/web/app_factory.py` | Wire config, services, repositories, Flask app construction, and route blueprints. | Embed policy rules or direct broker/data access. |
| Approval / entry policy | `services/policies/entry_policy.py`, `services/approval_service.py` | Deterministic entry gates, confirmation requirements, live-bias interpretation. | Submit orders or mutate persistence directly. |
| Sizing | `services/policies/sizing_policy.py`, `services/sizing_service.py` | Size caps, dominant limiter attribution, adaptive opportunity sizing. | Approve/reject trades or submit orders. |
| Execution | `services/policies/execution_policy.py`, `services/execution_service.py`, `services/broker_service.py` | Final safety checks, broker abstraction, order submission path. | Own entry scoring or HTTP request parsing. |
| Exits | `position_manager.py`, `position_momentum_monitor.py`, `services/policies/execution_policy.py` | Exit decisions, sell continuation checks, broker-side sell handling. | Bypass audit logging when running live execution paths. |
| Market data | `services/market_data_service.py`, `services/tape_service.py` | Bar/quote/trade reads, SIP-to-IEX fallback, live tape reads. | Encode approval or sizing policy. |
| Persistence | `repositories/*.py`, `decision_snapshots.py` | SQL access and audit records behind repository functions. | Import Flask, route modules, or broker clients. |
| Reporting / ops | `*_report.py`, `ops/*.md`, `morning_check.py`, `post_session_check.py` | Read-only diagnostics and scheduled operational checks. | Change runtime policy without an explicit policy artifact or config flag. |
| Observability / guardrails | `services/observability.py`, `services/policy_controls.py`, `tests/test_architecture_boundaries.py` | Runtime metrics, policy kill switches, import-boundary tests. | Submit orders or perform market-data reads. |

## Architecture Boundaries

Direct SQLite access is allowed only in:

- `db.py`
- `db_migrations.py`
- `repositories/`
- `migrations/`

All reports, builders, scripts, runtime services, and ops checks must use repository APIs instead of importing `db`, `get_connection`, or `sqlite3` directly.

Broker and external market-data access is allowed only in approved adapter boundaries:

- `broker.py`
- `services/broker_service.py`
- `services/market_data_service.py`
- approved execution, context, report-labeling, and market-data adapter services

Runtime scripts and reports should use those services rather than calling broker or market-data clients directly.

Flask belongs only in `app.py` and `api/`. Repositories, policies, live signal processing, and data services must not import Flask.

Policy modules are decision logic. They should consume facts passed in by context, execution, broker, or market-data services; they should not fetch data directly or mutate persistence.

The architecture boundary tests intentionally keep temporary allowlists empty. If a future migration needs a temporary exception, add an explicit TODO reason and remove it in the same cleanup sequence.

Policy families can be disabled without editing `app.py`:

- `POLICY_ENTRY_ENABLED=false`
- `POLICY_SIZING_ENABLED=false`
- `POLICY_EXECUTION_ENABLED=false`
- `POLICY_EXITS_ENABLED=false`
- `POLICY_REPORTING_ENABLED=false`
- `DISABLED_POLICY_FAMILIES=entry,sizing`

The `/status` payload exposes `policy_controls` and `runtime_metrics` so an operator can answer which policy family was active and what stages/fallbacks/limiters were involved in the current runtime.
