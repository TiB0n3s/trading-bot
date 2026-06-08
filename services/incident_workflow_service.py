"""Incident workflow helpers for operator-run diagnostics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class IncidentDraft:
    incident_id: str
    path: Path
    content: str
    created: bool


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled"


def build_incident_content(
    *,
    incident_id: str,
    title: str,
    severity: str,
    created_at: datetime | None = None,
) -> str:
    created_at = created_at or datetime.now(timezone.utc)
    iso_created = created_at.isoformat()
    return f"""# Incident Report

## Summary

- Incident ID: {incident_id}
- Title: {title}
- Severity: {severity}
- Status: open
- Started At: {iso_created}
- Resolved At:
- Owner:

## Impact

- Trading mode affected:
- Symbols affected:
- Orders affected:
- Data/learning affected:
- User/operator impact:

## Detection

- Detected by:
- First alert/report:
- Related commands:
  - `python3 ops_check.py observability-health {created_at.date().isoformat()}`
  - `python3 ops_check.py jobs`
  - `python3 ops_check.py runtime-health {created_at.date().isoformat()}`

## Timeline

- `{iso_created}` - Incident record opened.

## Root Cause

- Technical cause:
- Contributing factors:
- What made detection harder:

## Resolution

- Immediate mitigation:
- Permanent fix:
- Rollback used:

## Evidence Links

- Job run:
- Logs:
- Order/fill records:
- Learning artifacts:
- Model artifacts:
- Commit(s):

## Follow-Up Actions

- [ ] Action:
- [ ] Test/monitoring added:
- [ ] Documentation updated:

## Lessons

- What worked:
- What failed:
- What to change before cash-live authority:
"""


def create_incident_draft(
    *,
    base_dir: Path,
    title: str,
    severity: str = "medium",
    created_at: datetime | None = None,
    write: bool = False,
) -> IncidentDraft:
    created_at = created_at or datetime.now(timezone.utc)
    incident_id = f"incident_{created_at.strftime('%Y%m%dT%H%M%SZ')}_{_slugify(title)}"
    incident_dir = base_dir / "ops" / "incidents"
    path = incident_dir / f"{incident_id}.md"
    content = build_incident_content(
        incident_id=incident_id,
        title=title,
        severity=severity,
        created_at=created_at,
    )

    created = False
    if write:
        incident_dir.mkdir(parents=True, exist_ok=True)
        if path.exists():
            suffix = 2
            while True:
                candidate_id = f"{incident_id}_{suffix}"
                candidate_path = incident_dir / f"{candidate_id}.md"
                if not candidate_path.exists():
                    incident_id = candidate_id
                    path = candidate_path
                    content = build_incident_content(
                        incident_id=incident_id,
                        title=title,
                        severity=severity,
                        created_at=created_at,
                    )
                    break
                suffix += 1
        path.write_text(content, encoding="utf-8")
        created = True

    return IncidentDraft(
        incident_id=incident_id,
        path=path,
        content=content,
        created=created,
    )
