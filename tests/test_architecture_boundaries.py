#!/usr/bin/env python3
"""Architecture boundary tests for Phase 7 guardrails."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy")


def _python_files(directory: str) -> list[Path]:
    return sorted(
        path
        for path in (ROOT / directory).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return modules


def _assert_no_import(directory: str, banned: set[str], label: str):
    violations = []
    for path in _python_files(directory):
        for module in _imports(path):
            root = module.split(".", 1)[0]
            if module in banned or root in banned:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert_true(not violations, f"{label}: {violations}")


def test_api_cannot_import_broker_directly():
    _assert_no_import("api", {"broker"}, "api broker boundary")


def test_repositories_cannot_import_flask():
    _assert_no_import("repositories", {"flask"}, "repository Flask boundary")


def test_policies_cannot_import_routes():
    _assert_no_import("services/policies", {"api"}, "policy route boundary")


def main():
    tests = [
        test_api_cannot_import_broker_directly,
        test_repositories_cannot_import_flask,
        test_policies_cannot_import_routes,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} architecture boundary tests passed.")


if __name__ == "__main__":
    main()
