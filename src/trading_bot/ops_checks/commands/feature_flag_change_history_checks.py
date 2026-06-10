"""Operator report for feature-flag change history."""

from __future__ import annotations

from pathlib import Path

from services.feature_flag_change_history_service import (
    append_feature_flag_change_record,
    build_feature_flag_change_history_payload,
)


def run_feature_flag_change_history_report(
    *,
    base_dir: Path,
    append: bool = False,
    flag: str = "",
    old_value: str = "",
    new_value: str = "",
    operator: str = "",
    approval_reference: str = "",
    rollback_plan: str = "",
) -> bool:
    append_errors = []
    if append:
        if not flag:
            append_errors.append("flag_required")
        if not operator:
            append_errors.append("operator_required")
        if not approval_reference:
            append_errors.append("approval_reference_required")
        if not rollback_plan:
            append_errors.append("rollback_plan_required")
        if not append_errors:
            append_feature_flag_change_record(
                base_dir=base_dir,
                flag=flag,
                old_value=old_value,
                new_value=new_value,
                operator=operator,
                approval_reference=approval_reference,
                rollback_plan=rollback_plan,
            )
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
    if append_errors:
        print("append_errors           : " + ",".join(append_errors))
    print()
    for note in payload["notes"]:
        print(f"  note: {note}")
    print()
    if payload["ready"] and not append_errors:
        print("[OK] feature-flag change history is valid")
        return True
    print("[WARN] feature-flag change history has validation errors")
    return False
