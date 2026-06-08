#!/usr/bin/env python3
"""Dependency packaging contract tests."""

from __future__ import annotations

import sys
import tomllib
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
    "torch",
    "xgboost",
}
OPTIONAL_EXTRA_EXPECTATIONS = {
    "dashboard": {"streamlit"},
    "timescale": {"asyncpg"},
    "sentiment": {"transformers"},
}


def _pinned_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-r "):
            continue
        names.add(line.split("==", 1)[0].lower())
    return names


def _pyproject_extra_names(extra: str) -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = data["project"]["optional-dependencies"][extra]
    names = set()
    for item in dependencies:
        name = item.split("==", 1)[0].split(">=", 1)[0].split("<", 1)[0].lower()
        names.add(name)
    return names


def test_runtime_requirements_exclude_research_only_dependencies():
    base_names = _pinned_names(ROOT / "requirements-base.txt")

    assert RESEARCH_ONLY_PINS.isdisjoint(base_names)


def test_research_requirements_pin_intended_optional_ml_dependencies():
    research_names = _pinned_names(ROOT / "requirements-research.txt")

    assert RESEARCH_ONLY_PINS.issubset(research_names)


def test_pyproject_research_extra_matches_research_requirement_pins():
    research_names = _pinned_names(ROOT / "requirements-research.txt")
    pyproject_research = _pyproject_extra_names("research")

    assert RESEARCH_ONLY_PINS.issubset(pyproject_research)
    assert pyproject_research == research_names


def test_pyproject_declares_intended_optional_integration_extras():
    for extra, expected_names in OPTIONAL_EXTRA_EXPECTATIONS.items():
        assert expected_names.issubset(_pyproject_extra_names(extra))


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
        test_pyproject_research_extra_matches_research_requirement_pins,
        test_pyproject_declares_intended_optional_integration_extras,
        test_legacy_requirements_delegate_to_research_requirements,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} dependency packaging contract tests passed.")


if __name__ == "__main__":
    main()
