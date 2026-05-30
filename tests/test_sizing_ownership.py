#!/usr/bin/env python3
"""Guardrails for sizing ownership during the app split."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def assert_true(value, label):
    if not value:
        raise AssertionError(label)


def test_app_does_not_directly_assign_max_position_size_override():
    tree = ast.parse((ROOT / "app.py").read_text(), filename="app.py")
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        targets = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        else:
            targets = [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "max_position_size_pct_override"
            ):
                violations.append(node.lineno)
    assert_true(not violations, f"app.py directly assigns max_position_size_pct_override at {violations}")


def main():
    tests = [test_app_does_not_directly_assign_max_position_size_override]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} sizing ownership tests passed.")


if __name__ == "__main__":
    main()
