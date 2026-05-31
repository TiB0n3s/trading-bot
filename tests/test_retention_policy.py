#!/usr/bin/env python3

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_platform.retention import retention_policy


def test_retention_policy_classifies_new_ml_tables():
    policy = retention_policy()
    names = {row["name"]: row for row in policy["rules"]}

    required = {
        "feature_snapshots",
        "labeled_setups",
        "rejected_signal_outcomes",
        "auto_buy_candidates",
        "decision_snapshots",
        "exit_snapshots",
        "bot_events",
    }
    missing = required - set(names)
    if missing:
        raise AssertionError(f"missing retention rules: {sorted(missing)}")

    if policy["destructive_compaction_enabled"] is not False:
        raise AssertionError("retention policy should not enable destructive compaction")

    if names["decision_snapshots"]["tier"] != "cold":
        raise AssertionError("decision_snapshots should be cold archival data")
    if names["exit_snapshots"]["tier"] != "cold":
        raise AssertionError("exit_snapshots should be cold archival data")


if __name__ == "__main__":
    test_retention_policy_classifies_new_ml_tables()
    print("[OK] retention policy tests passed")
