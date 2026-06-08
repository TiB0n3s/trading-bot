#!/usr/bin/env python3
"""Formal label v1 builder contract for feature snapshots.

This wraps the existing label_features implementation with explicit label
taxonomy/version metadata and leakage checks. It preserves the current
`labeled_setups` schema while making the generation contract auditable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.label_v1_repo import LabelV1Repository

LABEL_BUILDER_VERSION = "label_v1_builder_20260527"
LABEL_VERSION = "label_taxonomy_v1"
EXIT_POLICY_VERSION = "fixed_horizon_v1_no_realized_exit"
POSITION_MANAGER_VERSION = "not_applicable_fixed_horizon"
_repo = LabelV1Repository()


def validate_feature_snapshot_contract(db_path: Path | str | None = None) -> dict[str, Any]:
    repo = LabelV1Repository(db_path) if db_path is not None else _repo
    cols = repo.feature_snapshot_columns()
    required = {
        "feature_available_at",
        "feature_generated_at",
        "feature_age_seconds",
        "source",
        "is_stale",
        "staleness_reason",
    }
    missing = sorted(required - cols)
    stale_count = repo.stale_feature_snapshot_count() if not missing else 0
    return {
        "ok": not missing,
        "missing_feature_audit_fields": missing,
        "stale_feature_snapshot_count": stale_count,
        "label_builder_version": LABEL_BUILDER_VERSION,
        "label_version": LABEL_VERSION,
        "exit_policy_version": EXIT_POLICY_VERSION,
        "position_manager_version": POSITION_MANAGER_VERSION,
    }


def build_labels(limit: int = 200) -> dict[str, Any]:
    contract = validate_feature_snapshot_contract()
    if not contract["ok"]:
        return {
            "status": "blocked",
            "reason": "feature_snapshots missing leakage/audit fields",
            **contract,
        }

    before = _label_count()
    rc = subprocess.run(
        [sys.executable, "label_features.py"],
        cwd=Path(__file__).resolve().parent,
    ).returncode
    after = _label_count()
    return {
        "status": "complete" if rc == 0 else "failed",
        "return_code": rc,
        "labels_before": before,
        "labels_after": after,
        "labels_added": after - before,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **contract,
    }


def _label_count() -> int:
    return _repo.label_count()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=200, help="Reserved for future builder-owned batching"
    )
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    result = validate_feature_snapshot_contract() if args.check_only else build_labels(args.limit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok", result.get("status") == "complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
