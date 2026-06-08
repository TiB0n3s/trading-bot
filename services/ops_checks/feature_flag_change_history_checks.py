"""Operator report for feature-flag change history."""

from __future__ import annotations

from pathlib import Path

from services.feature_flag_change_history_service import (
    build_feature_flag_change_history_payload,
)


def run_feature_flag_change_history_report(*, base_dir: Path) -> bool:
    payload = build_feature_flag_change_history_payload(base_dir=base_dir)
    print()
    print("=" * 72)
    print("  Feature-Flag Change History")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"history_path            : {payload['history_path']}")
    print(f"record_count            : {payload['record_count']}")
    print(f"cash_live_record_count  : {payload['cash_live_record_count']}")
    print("errors                  : " + (",".join(payload["errors"]) or "-"))
    print()
    for note in payload["notes"]:
        print(f"  note: {note}")
    print()
    if payload["ready"]:
        print("[OK] feature-flag change history is valid")
        return True
    print("[WARN] feature-flag change history has validation errors")
    return False
