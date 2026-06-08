#!/usr/bin/env python3
"""Tests for incident workflow helpers."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.incident_workflow_service import create_incident_draft  # noqa: E402


def test_create_incident_draft_renders_required_sections_without_writing():
    with TemporaryDirectory() as tmp:
        draft = create_incident_draft(
            base_dir=Path(tmp),
            title="DB lock during backfill",
            severity="high",
            created_at=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
            write=False,
        )

    assert draft.created is False
    assert "incident_20260608T120000Z_db-lock-during-backfill" in draft.incident_id
    assert "- Severity: high" in draft.content
    assert "## Follow-Up Actions" in draft.content
    assert "ops_check.py observability-health 2026-06-08" in draft.content


def test_create_incident_draft_writes_without_overwriting_existing_file():
    with TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        created_at = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        first = create_incident_draft(
            base_dir=base_dir,
            title="DB lock during backfill",
            severity="high",
            created_at=created_at,
            write=True,
        )
        second = create_incident_draft(
            base_dir=base_dir,
            title="DB lock during backfill",
            severity="high",
            created_at=created_at,
            write=True,
        )

    assert first.created is True
    assert second.created is True
    assert first.path != second.path
    assert first.path.name.endswith(".md")
    assert second.path.name.endswith("_2.md")


def main():
    tests = [
        test_create_incident_draft_renders_required_sections_without_writing,
        test_create_incident_draft_writes_without_overwriting_existing_file,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} incident workflow tests passed.")


if __name__ == "__main__":
    main()
