#!/usr/bin/env python3
"""Dependency packaging contract tests."""

from __future__ import annotations

import importlib.util
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
DEV_ONLY_PINS = {
    "mypy",
    "pip-audit",
    "pre-commit",
    "pytest",
    "pytest-xdist",
    "ruff",
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


def test_default_requirements_delegate_to_runtime_requirements():
    lines = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert lines == ["-r requirements-base.txt"]


def test_research_and_dev_requirements_are_overlays_only():
    research_lines = (ROOT / "requirements-research.txt").read_text(encoding="utf-8").splitlines()
    dev_lines = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()

    assert all(not line.strip().startswith("-r ") for line in research_lines if line.strip())
    assert all(not line.strip().startswith("-r ") for line in dev_lines if line.strip())


def test_research_requirements_pin_intended_optional_ml_dependencies():
    research_names = _pinned_names(ROOT / "requirements-research.txt")

    assert RESEARCH_ONLY_PINS.issubset(research_names)


def test_pyproject_research_extra_matches_research_requirement_pins():
    research_names = _pinned_names(ROOT / "requirements-research.txt")
    pyproject_research = _pyproject_extra_names("research")

    assert RESEARCH_ONLY_PINS.issubset(pyproject_research)
    assert pyproject_research == research_names


def test_pyproject_runtime_extra_matches_runtime_requirement_pins():
    base_names = _pinned_names(ROOT / "requirements-base.txt")
    pyproject_runtime = _pyproject_extra_names("runtime")

    assert pyproject_runtime == base_names


def test_pyproject_dev_extra_matches_dev_requirement_pins():
    dev_names = _pinned_names(ROOT / "requirements-dev.txt")
    pyproject_dev = _pyproject_extra_names("dev")

    assert DEV_ONLY_PINS.issubset(dev_names)
    assert pyproject_dev == dev_names


def test_pyproject_declares_intended_optional_integration_extras():
    for extra, expected_names in OPTIONAL_EXTRA_EXPECTATIONS.items():
        assert expected_names.issubset(_pyproject_extra_names(extra))


def test_trading_bot_package_imports_without_src_prefix():
    spec = importlib.util.find_spec("trading_bot")

    assert spec is not None
    assert spec.origin is not None
    assert "/src/trading_bot/" in spec.origin


def main():
    tests = [
        test_runtime_requirements_exclude_research_only_dependencies,
        test_default_requirements_delegate_to_runtime_requirements,
        test_research_and_dev_requirements_are_overlays_only,
        test_research_requirements_pin_intended_optional_ml_dependencies,
        test_pyproject_research_extra_matches_research_requirement_pins,
        test_pyproject_runtime_extra_matches_runtime_requirement_pins,
        test_pyproject_dev_extra_matches_dev_requirement_pins,
        test_pyproject_declares_intended_optional_integration_extras,
        test_trading_bot_package_imports_without_src_prefix,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} dependency packaging contract tests passed.")


if __name__ == "__main__":
    main()
