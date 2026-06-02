#!/usr/bin/env python3
"""Tests for optional AI dependency readiness."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.optional_dependency_service import optional_dependency_status


def test_optional_dependency_status_reports_packages_without_importing():
    status = optional_dependency_status()

    assert status["runtime_effect"] == "readiness_only_no_import_side_effects"
    assert "sklearn" in status["packages"]
    assert "transformers" in status["packages"]
    assert status["missing_count"] + status["available_count"] == len(status["packages"])


def main():
    test_optional_dependency_status_reports_packages_without_importing()
    print("[OK] test_optional_dependency_status_reports_packages_without_importing")
    print("\nAll 1 optional dependency service tests passed.")


if __name__ == "__main__":
    main()
