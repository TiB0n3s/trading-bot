"""Runtime, operations, and observability ops-check command specs."""

from __future__ import annotations

from trading_bot.ops_checks.commands.base import OpsCommandSpec, noarg, spec

COMMAND_SPECS: dict[str, OpsCommandSpec] = {
    "jobs": noarg("jobs", "jobs_status"),
    "job": spec("job", "jobs_status", "job_filter"),
    "market-context-check": noarg("market-context-check", "check_market_context_file"),
    "intelligence-summary": spec("intelligence-summary"),
    "dataset-health": spec("dataset-health"),
    "feature-health": spec("feature-health"),
    "feature-watch": spec("feature-watch"),
    "decision-snapshots": spec("decision-snapshots", "decision_snapshot_health"),
    "audit-write-integrity": spec("audit-write-integrity", "audit_write_integrity"),
    "policy-artifacts": noarg("policy-artifacts", "policy_artifact_health"),
    "retention": noarg("retention", "retention_health"),
    "order-health": spec("order-health"),
    "runtime-health": spec("runtime-health"),
    "runtime-health-trend": spec(
        "runtime-health-trend", "runtime_health_trend", "target_date", "end_date"
    ),
    "observability-health": spec("observability-health"),
    "operational-readiness": spec("operational-readiness", "run_operational_readiness"),
    "log-ledger-consistency": noarg("log-ledger-consistency"),
    "production-evidence": spec("production-evidence"),
    "database-backups": noarg("database-backups"),
    "database-restore-drill": noarg("database-restore-drill"),
    "paper-replay-load-probe": noarg("paper-replay-load-probe"),
    "full-session-paper-replay": noarg("full-session-paper-replay"),
    "incident-workflow": noarg("incident-workflow"),
    "incident-escalation-readiness": noarg("incident-escalation-readiness"),
    "external-observability-readiness": noarg("external-observability-readiness"),
    "feature-flag-change-history": noarg("feature-flag-change-history"),
    "packaged-entrypoints": noarg("packaged-entrypoints"),
    "model-promotion-evidence": noarg("model-promotion-evidence"),
    "resource-readiness": noarg("resource-readiness"),
    "monday-readiness": noarg("monday-readiness", "monday_readiness"),
    "sqlite-ownership": noarg("sqlite-ownership", "sqlite_ownership"),
    "migration-status": noarg("migration-status", "migration_status_check"),
}
