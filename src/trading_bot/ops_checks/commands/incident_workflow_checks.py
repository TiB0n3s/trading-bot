"""Operator incident workflow command."""

from __future__ import annotations

from pathlib import Path

from services.incident_workflow_service import create_incident_draft


def run_incident_workflow_report(
    *,
    base_dir: Path,
    title: str,
    severity: str = "medium",
    create: bool = False,
) -> bool:
    draft = create_incident_draft(
        base_dir=base_dir,
        title=title,
        severity=severity,
        write=create,
    )

    print()
    print("=" * 72)
    print("  Incident Workflow")
    print("=" * 72)
    print("report_version          : incident_workflow_v1")
    print("runtime_effect          : operator_record_only_no_runtime_change")
    print(f"incident_id             : {draft.incident_id}")
    print(f"path                    : {draft.path}")
    print(f"created                 : {draft.created}")
    print()
    if create:
        print("[OK] incident record created")
    else:
        print("[OK] incident draft rendered; add --create to write it")
        print()
        print(draft.content)
    return True
