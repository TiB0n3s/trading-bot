"""Learning, intelligence, education, and model ops-check command specs."""

from __future__ import annotations

from trading_bot.ops_checks.commands.base import OpsCommandSpec, noarg, spec

COMMAND_SPECS: dict[str, OpsCommandSpec] = {
    "model-governance": noarg("model-governance"),
    "trading-education-health": noarg("trading-education-health"),
    "trading-education-ingest": noarg("trading-education-ingest"),
    "trading-education-review": noarg("trading-education-review"),
    "trading-education-coverage": noarg("trading-education-coverage"),
    "research-export": spec("research-export"),
    "lifecycle-analysis": spec("lifecycle-analysis"),
    "decision-lifecycle-dashboard": spec("decision-lifecycle-dashboard"),
    "decision-quality-review": spec("decision-quality-review"),
    "candidate-universe": spec("candidate-universe"),
    "candidate-outcome-backfill": spec("candidate-outcome-backfill"),
    "missed-buy-review": spec("missed-buy-review"),
    "calibration-buckets": spec("calibration-buckets"),
    "feature-attribution": spec("feature-attribution"),
    "post-trade-learning": spec("post-trade-learning"),
    "symbol-patterns": spec("symbol-patterns"),
    "pattern-learning-inputs": spec("pattern-learning-inputs"),
    "ml-dataset-export": spec("ml-dataset-export", "ml_dataset_export"),
    "operator-intelligence": spec("operator-intelligence"),
    "learning-readiness": spec("learning-readiness"),
    "learning-effectiveness": spec("learning-effectiveness"),
    "learning-artifacts": spec("learning-artifacts"),
    "active-learning": spec("active-learning"),
    "rollout-contract": spec("rollout-contract"),
    "ai-intelligence-review": spec("ai-intelligence-review"),
    "point-in-time-archive": spec("point-in-time-archive"),
    "setup-breakdown": spec("setup-breakdown"),
    "winner-became-loser": spec("winner-became-loser"),
    "peak-bucket-report": spec("peak-bucket-report", "peak_bucket_report", "optional_date_arg"),
    "conviction-stack-report": spec("conviction-stack-report"),
    "conviction-persistence-health": spec("conviction-persistence-health"),
    "buy-opportunity-report": spec("buy-opportunity-report"),
    "claude-context-audit": spec("claude-context-audit"),
    "advisory-authority-report": spec("advisory-authority-report"),
    "paper-learning-authority": spec("paper-learning-authority"),
    "cross-layer-verification": spec("cross-layer-verification"),
}
