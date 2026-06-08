"""Feature-flag change-history validation for cash-live controls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = {
    "timestamp",
    "flag",
    "old_value",
    "new_value",
    "operator",
    "approval_reference",
    "rollback_plan",
}


def _load_records(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], ["history_file_missing"]
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line_{line_no}:invalid_json")
            continue
        if not isinstance(payload, dict):
            errors.append(f"line_{line_no}:not_object")
            continue
        missing = sorted(REQUIRED_FIELDS - set(payload))
        if missing:
            errors.append(f"line_{line_no}:missing:{','.join(missing)}")
        records.append(payload)
    return records, errors


def build_feature_flag_change_history_payload(*, base_dir: Path) -> dict[str, Any]:
    path = base_dir / "ops" / "feature_flag_change_history.jsonl"
    records, errors = _load_records(path)
    cash_live_records = [
        row
        for row in records
        if str(row.get("flag") or "").upper()
        in {"LIVE_TRADING_ENABLED", "AUTO_BUY_LIVE_BUYS", "TRANSFORMER_AUTHORITY_ENABLED"}
        or "LIVE" in str(row.get("flag") or "").upper()
    ]
    return {
        "report_version": "feature_flag_change_history_v1",
        "runtime_effect": "diagnostic_only_no_runtime_config_change",
        "history_path": str(path),
        "record_count": len(records),
        "cash_live_record_count": len(cash_live_records),
        "errors": errors,
        "ready": path.exists() and not errors,
        "notes": [
            "Append one JSON object per operator-approved cash-live flag change.",
            "An empty file is valid when no cash-live flag changes have occurred.",
        ],
    }
