"""Retention classification for ML/audit tables.

This is intentionally non-destructive. It gives operators a shared vocabulary
before compaction/archive commands are allowed to delete or move data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RetentionRule:
    name: str
    tier: str
    default_window_days: int | None
    storage: str
    rationale: str


RETENTION_RULES: tuple[RetentionRule, ...] = (
    RetentionRule(
        "trades",
        "hot",
        120,
        "main_sqlite",
        "Runtime/reporting source for approved and rejected decisions.",
    ),
    RetentionRule(
        "fill_events",
        "warm",
        120,
        "main_sqlite_then_archive",
        "Order/fill integrity and reconstruction evidence.",
    ),
    RetentionRule(
        "feature_snapshots",
        "warm",
        45,
        "main_sqlite_then_archive",
        "High-volume intraday ML features; needed for recent labels and daily QA.",
    ),
    RetentionRule(
        "labeled_setups",
        "warm",
        120,
        "main_sqlite_then_archive",
        "Fixed-horizon labels used by evaluation and model research.",
    ),
    RetentionRule(
        "rejected_signal_outcomes",
        "cold",
        None,
        "archive_or_separate_sqlite",
        "Counterfactual labels should be retained for replay, but not queried in runtime paths.",
    ),
    RetentionRule(
        "auto_buy_candidates",
        "warm",
        90,
        "main_sqlite_then_archive",
        "Internal candidate evidence for TradingView-vs-bar-source comparison.",
    ),
    RetentionRule(
        "decision_snapshots",
        "cold",
        None,
        "archive_or_separate_sqlite",
        "Immutable replay/audit trail; preserve rather than compact destructively.",
    ),
    RetentionRule(
        "exit_snapshots",
        "cold",
        None,
        "archive_or_separate_sqlite",
        "Immutable exit-learning trail; preserve for post-exit recovery and capture analysis.",
    ),
    RetentionRule(
        "bot_events",
        "warm",
        120,
        "main_sqlite_then_archive",
        "Operational event timeline used by daily checks and incident review.",
    ),
    RetentionRule(
        "daily_symbol_context",
        "warm",
        180,
        "main_sqlite_then_archive",
        "Premarket intelligence context used by research joins.",
    ),
    RetentionRule(
        "daily_symbol_events",
        "warm",
        180,
        "main_sqlite_then_archive",
        "Event/catalyst feature source.",
    ),
    RetentionRule(
        "daily_symbol_predictions",
        "warm",
        180,
        "main_sqlite_then_archive",
        "Observe-only prediction history and validation source.",
    ),
    RetentionRule(
        "schema_migrations",
        "hot",
        None,
        "main_sqlite",
        "Schema status must stay with the database.",
    ),
)


def retention_policy() -> dict[str, Any]:
    return {
        "version": "retention_policy_v1",
        "destructive_compaction_enabled": False,
        "rule": "Do not delete or move ML/audit rows until archive restore has been tested.",
        "rules": [asdict(rule) for rule in RETENTION_RULES],
    }
