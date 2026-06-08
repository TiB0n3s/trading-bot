"""Command registry for operator checks.

The root ``ops_check.py`` script still owns many legacy helper functions. This
module keeps the command surface data-driven so new checks do not require
another long ``if command == ...`` chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

HandlerMap = Mapping[str, Callable[..., bool]]


@dataclass(frozen=True)
class OpsCommandSpec:
    command: str
    handler_name: str
    arg_tokens: tuple[str, ...] = ("target_date",)

    def run(self, handlers: HandlerMap, args: Mapping[str, object]) -> bool:
        handler = handlers[self.handler_name]
        resolved_args = [args[token] for token in self.arg_tokens]
        return bool(handler(*resolved_args))


def _spec(
    command: str,
    handler_name: str | None = None,
    *arg_tokens: str,
) -> OpsCommandSpec:
    return OpsCommandSpec(
        command=command,
        handler_name=handler_name or command.replace("-", "_"),
        arg_tokens=tuple(arg_tokens) or ("target_date",),
    )


def _noarg(command: str, handler_name: str | None = None) -> OpsCommandSpec:
    return OpsCommandSpec(
        command=command,
        handler_name=handler_name or command.replace("-", "_"),
        arg_tokens=(),
    )


OPS_COMMAND_SPECS: dict[str, OpsCommandSpec] = {
    "jobs": _noarg("jobs", "jobs_status"),
    "job": _spec("job", "jobs_status", "job_filter"),
    "market-context-check": _noarg("market-context-check", "check_market_context_file"),
    "intelligence-summary": _spec("intelligence-summary"),
    "dataset-health": _spec("dataset-health"),
    "feature-health": _spec("feature-health"),
    "feature-watch": _spec("feature-watch"),
    "live-bar-pattern-capture": _spec("live-bar-pattern-capture"),
    "rejection-summary": _spec("rejection-summary"),
    "rejected-outcomes": _spec("rejected-outcomes", "rejected_outcomes_health"),
    "auto-buy": _spec("auto-buy", "auto_buy_health"),
    "signal-source-readiness": _spec("signal-source-readiness"),
    "decision-snapshots": _spec("decision-snapshots", "decision_snapshot_health"),
    "policy-artifacts": _noarg("policy-artifacts", "policy_artifact_health"),
    "retention": _noarg("retention", "retention_health"),
    "order-health": _spec("order-health"),
    "runtime-health": _spec("runtime-health"),
    "runtime-health-trend": _spec(
        "runtime-health-trend", "runtime_health_trend", "target_date", "end_date"
    ),
    "observability-health": _spec("observability-health"),
    "context-freshness": _spec("context-freshness"),
    "data-freshness-gate": _spec("data-freshness-gate"),
    "event-source-coverage": _spec("event-source-coverage"),
    "event-context-validation": _spec("event-context-validation"),
    "external-symbol-discovery": _spec("external-symbol-discovery"),
    "external-symbol-candidates": _noarg("external-symbol-candidates"),
    "log-ledger-consistency": _noarg("log-ledger-consistency"),
    "portfolio-risk": _spec("portfolio-risk"),
    "production-evidence": _spec("production-evidence"),
    "config-audit": _noarg("config-audit"),
    "feature-flags": _noarg("feature-flags"),
    "model-governance": _noarg("model-governance"),
    "secrets-hygiene": _noarg("secrets-hygiene"),
    "architecture-surface": _noarg("architecture-surface"),
    "database-backups": _noarg("database-backups"),
    "local-load-probe": _noarg("local-load-probe"),
    "paper-replay-load-probe": _noarg("paper-replay-load-probe"),
    "incident-workflow": _noarg("incident-workflow"),
    "external-observability-readiness": _noarg("external-observability-readiness"),
    "secrets-manager-readiness": _noarg("secrets-manager-readiness"),
    "resource-readiness": _noarg("resource-readiness"),
    "advanced-alpha-readiness": _spec("advanced-alpha-readiness"),
    "advanced-alpha-comparison": _spec("advanced-alpha-comparison"),
    "friction-heatmap": _spec("friction-heatmap"),
    "volume-clock-vpin": _spec("volume-clock-vpin"),
    "volatile-session-intelligence": _spec("volatile-session-intelligence"),
    "cross-asset-lead-map": _noarg("cross-asset-lead-map", "cross_asset_lead_map"),
    "transformer-authority": _noarg("transformer-authority"),
    "trading-education-health": _noarg("trading-education-health"),
    "trading-education-ingest": _noarg("trading-education-ingest"),
    "trading-education-review": _noarg("trading-education-review"),
    "trading-education-coverage": _noarg("trading-education-coverage"),
    "market-data-parity": _spec("market-data-parity", "market_data_parity", "symbol_arg"),
    "research-export": _spec("research-export"),
    "shadow-predictions": _spec("shadow-predictions"),
    "lifecycle-analysis": _spec("lifecycle-analysis"),
    "decision-lifecycle-dashboard": _spec("decision-lifecycle-dashboard"),
    "decision-quality-review": _spec("decision-quality-review"),
    "exit-snapshot-backfill": _spec("exit-snapshot-backfill"),
    "candidate-universe": _spec("candidate-universe"),
    "candidate-outcome-backfill": _spec("candidate-outcome-backfill"),
    "missed-buy-review": _spec("missed-buy-review"),
    "calibration-buckets": _spec("calibration-buckets"),
    "feature-attribution": _spec("feature-attribution"),
    "post-trade-learning": _spec("post-trade-learning"),
    "symbol-patterns": _spec("symbol-patterns"),
    "pattern-learning-inputs": _spec("pattern-learning-inputs"),
    "bar-pattern-backfill": _spec("bar-pattern-backfill"),
    "historical-bar-archive": _spec("historical-bar-archive"),
    "historical-bar-coverage": _spec(
        "historical-bar-coverage", "historical_bar_coverage", "start_arg"
    ),
    "historical-bar-progress": _spec(
        "historical-bar-progress", "historical_bar_progress", "start_arg"
    ),
    "historical-bar-readiness": _spec(
        "historical-bar-readiness", "historical_bar_readiness", "start_arg"
    ),
    "historical-bar-models": _noarg("historical-bar-models", "historical_bar_models"),
    "historical-bar-paper-strategy": _spec(
        "historical-bar-paper-strategy", "historical_bar_paper_strategy"
    ),
    "historical-bar-paper-validation": _spec(
        "historical-bar-paper-validation", "historical_bar_paper_validation"
    ),
    "historical-bar-walk-forward": _spec(
        "historical-bar-walk-forward", "historical_bar_walk_forward"
    ),
    "historical-bar-validation": _spec("historical-bar-validation", "historical_bar_validation"),
    "ml-dataset-export": _spec("ml-dataset-export", "ml_dataset_export"),
    "monday-readiness": _noarg("monday-readiness", "monday_readiness"),
    "exit-intelligence": _spec("exit-intelligence"),
    "sqlite-ownership": _noarg("sqlite-ownership", "sqlite_ownership"),
    "operator-intelligence": _spec("operator-intelligence"),
    "learning-readiness": _spec("learning-readiness"),
    "learning-effectiveness": _spec("learning-effectiveness"),
    "learning-artifacts": _spec("learning-artifacts"),
    "active-learning": _spec("active-learning"),
    "rollout-contract": _spec("rollout-contract"),
    "ai-intelligence-review": _spec("ai-intelligence-review"),
    "point-in-time-archive": _spec("point-in-time-archive"),
    "migration-status": _noarg("migration-status", "migration_status_check"),
    "setup-breakdown": _spec("setup-breakdown"),
    "winner-became-loser": _spec("winner-became-loser"),
    "peak-bucket-report": _spec("peak-bucket-report", "peak_bucket_report", "optional_date_arg"),
    "conviction-stack-report": _spec("conviction-stack-report"),
    "conviction-persistence-health": _spec("conviction-persistence-health"),
    "buy-opportunity-report": _spec("buy-opportunity-report"),
    "claude-context-audit": _spec("claude-context-audit"),
    "advisory-authority-report": _spec("advisory-authority-report"),
    "paper-learning-authority": _spec("paper-learning-authority"),
}


def build_command_args(argv: list[str], target_date: str) -> dict[str, object]:
    return {
        "target_date": target_date,
        "job_filter": argv[2] if len(argv) > 2 else None,
        "end_date": argv[3] if len(argv) > 3 and not argv[3].startswith("--") else target_date,
        "symbol_arg": argv[2] if len(argv) > 2 else "",
        "start_arg": argv[2] if len(argv) > 2 and not argv[2].startswith("--") else None,
        "optional_date_arg": argv[2] if len(argv) > 2 else None,
    }
