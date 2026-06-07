#!/usr/bin/env python3
"""Dependency packaging contract tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


RESEARCH_ONLY_PINS = {
    "duckdb",
    "hmmlearn",
    "joblib",
    "pyarrow",
    "scikit-learn",
    "scipy",
    "threadpoolctl",
    "xgboost",
}


def _pinned_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-r "):
            continue
        names.add(line.split("==", 1)[0].lower())
    return names


def test_runtime_requirements_exclude_research_only_dependencies():
    base_names = _pinned_names(ROOT / "requirements-base.txt")

    assert RESEARCH_ONLY_PINS.isdisjoint(base_names)


def test_research_requirements_pin_intended_optional_ml_dependencies():
    research_names = _pinned_names(ROOT / "requirements-research.txt")

    assert RESEARCH_ONLY_PINS.issubset(research_names)


def test_legacy_requirements_delegate_to_research_requirements():
    lines = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert lines == ["-r requirements-research.txt"]


def main():
    tests = [
        test_runtime_requirements_exclude_research_only_dependencies,
        test_research_requirements_pin_intended_optional_ml_dependencies,
        test_legacy_requirements_delegate_to_research_requirements,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nAll 3 dependency packaging contract tests passed.")


if __name__ == "__main__":
    main()
