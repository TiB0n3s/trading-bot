"""Repository wrapper for decision snapshot persistence."""

from __future__ import annotations

from decision_snapshots import record_decision_snapshot


def record_snapshot(**kwargs):
    return record_decision_snapshot(**kwargs)

