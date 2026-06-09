#!/usr/bin/env python3
"""Market-context writers must target the live root file by default."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _assign_names(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text())
    assignments: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
    return assignments


def _assert_root_output_file(script_name: str) -> None:
    path = ROOT / "scripts" / script_name
    assignments = _assign_names(path)
    assert "BASE_DIR" in assignments, f"{script_name} must define BASE_DIR"
    output = assignments.get("OUTPUT_FILE")
    assert isinstance(output, ast.BinOp), f"{script_name} OUTPUT_FILE must be a path expression"
    assert isinstance(output.left, ast.Name), f"{script_name} OUTPUT_FILE must use BASE_DIR"
    assert output.left.id == "BASE_DIR", f"{script_name} writes market_context outside repo root"
    assert isinstance(output.right, ast.Constant)
    assert output.right.value == "market_context.json"


def test_live_market_context_writers_target_repo_root():
    for script_name in (
        "pre_market_research_data.py",
        "intraday_context_refresh.py",
        "parse_market_brief.py",
        "pre_market_research.py",
    ):
        _assert_root_output_file(script_name)


def test_pre_market_pipeline_uses_root_relative_build_output():
    from pipeline.pre_market import _build_steps

    research = _build_steps("2026-06-09")[0]
    assert research.name == "research_data"
    build_output_index = research.argv.index("--build-output") + 1
    assert research.argv[build_output_index] == "market_context.json"


def main():
    tests = [
        test_live_market_context_writers_target_repo_root,
        test_pre_market_pipeline_uses_root_relative_build_output,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} market-context output path tests passed.")


if __name__ == "__main__":
    main()
