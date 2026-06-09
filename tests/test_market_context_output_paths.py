#!/usr/bin/env python3
"""Runtime JSON writers must target the live root files by default."""

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


def _assert_base_dir_is_repo_root(script_name: str) -> None:
    path = ROOT / "scripts" / script_name
    assignments = _assign_names(path)
    base_dir = assignments.get("BASE_DIR")
    if isinstance(base_dir, ast.Subscript):
        assert isinstance(base_dir.value, ast.Attribute), (
            f"{script_name} BASE_DIR must use parents[1]"
        )
        assert base_dir.value.attr == "parents", f"{script_name} BASE_DIR must use parents[1]"
        assert isinstance(base_dir.slice, ast.Constant), (
            f"{script_name} BASE_DIR must use parents[1]"
        )
        assert base_dir.slice.value == 1, f"{script_name} BASE_DIR must resolve to repo root"
        return

    if isinstance(base_dir, ast.Attribute):
        assert base_dir.attr == "parent", f"{script_name} BASE_DIR must resolve to repo root"
        assert isinstance(base_dir.value, ast.Name), (
            f"{script_name} BASE_DIR must resolve to repo root"
        )
        assert base_dir.value.id == "SCRIPT_DIR", (
            f"{script_name} BASE_DIR must resolve to repo root"
        )
        script_dir = assignments.get("SCRIPT_DIR")
        assert isinstance(script_dir, ast.Attribute), (
            f"{script_name} SCRIPT_DIR must use file parent"
        )
        assert script_dir.attr == "parent", f"{script_name} SCRIPT_DIR must use file parent"
        return

    raise AssertionError(f"{script_name} BASE_DIR must resolve to repo root")


def _assert_root_output_file(script_name: str, variable_name: str, filename: str) -> None:
    path = ROOT / "scripts" / script_name
    assignments = _assign_names(path)
    assert "BASE_DIR" in assignments, f"{script_name} must define BASE_DIR"
    _assert_base_dir_is_repo_root(script_name)
    output = assignments.get(variable_name)
    assert isinstance(output, ast.BinOp), f"{script_name} {variable_name} must be a path expression"
    assert isinstance(output.left, ast.Name), f"{script_name} {variable_name} must use BASE_DIR"
    assert output.left.id == "BASE_DIR", f"{script_name} writes runtime JSON outside repo root"
    assert isinstance(output.right, ast.Constant)
    assert output.right.value == filename


def test_live_market_context_writers_target_repo_root():
    for script_name in (
        "pre_market_research_data.py",
        "intraday_context_refresh.py",
        "parse_market_brief.py",
        "pre_market_research.py",
    ):
        _assert_root_output_file(script_name, "OUTPUT_FILE", "market_context.json")


def test_runtime_json_writers_target_repo_root():
    for script_name, variable_name, filename in (
        ("rolling_momentum.py", "OUTPUT_FILE", "rolling_momentum.json"),
        ("position_manager.py", "STATE_FILE", "position_manager_state.json"),
        ("portfolio_replacement_memory.py", "MEMORY_FILE", "portfolio_replacement_memory.json"),
        ("portfolio_rotation_manager.py", "MEMORY_FILE", "portfolio_replacement_memory.json"),
        (
            "portfolio_replacement_report.py",
            "PORTFOLIO_REPLACEMENT_MEMORY_FILE",
            "portfolio_replacement_memory.json",
        ),
        ("strategy_learner.py", "OUT_FILE", "strategy_memory.json"),
        ("symbol_momentum_timing_report.py", "MEMORY_FILE", "symbol_momentum_timing_memory.json"),
        ("missed_opportunity_report.py", "MISSED_MEMORY_FILE", "missed_opportunity_memory.json"),
        ("excursion_report.py", "EXCURSION_MEMORY_FILE", "excursion_memory.json"),
        ("policy_backtest.py", "POLICY_BACKTEST_SUMMARY_FILE", "policy_backtest_summary.json"),
    ):
        _assert_root_output_file(script_name, variable_name, filename)


def test_scripts_directory_has_no_runtime_json_duplicates():
    runtime_names = {
        "excursion_memory.json",
        "market_context.json",
        "missed_opportunity_memory.json",
        "policy_backtest_summary.json",
        "portfolio_replacement_memory.json",
        "position_manager_state.json",
        "rolling_momentum.json",
        "strategy_memory.json",
        "symbol_momentum_timing_memory.json",
        "symbol_overrides.json",
    }
    duplicates = sorted(
        path.name for path in (ROOT / "scripts").glob("*.json") if path.name in runtime_names
    )
    assert duplicates == [], f"runtime JSON duplicates under scripts/: {duplicates}"


def test_pre_market_pipeline_uses_root_relative_build_output():
    from pipeline.pre_market import _build_steps

    research = _build_steps("2026-06-09")[0]
    assert research.name == "research_data"
    build_output_index = research.argv.index("--build-output") + 1
    assert research.argv[build_output_index] == "market_context.json"


def main():
    tests = [
        test_live_market_context_writers_target_repo_root,
        test_runtime_json_writers_target_repo_root,
        test_scripts_directory_has_no_runtime_json_duplicates,
        test_pre_market_pipeline_uses_root_relative_build_output,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} market-context output path tests passed.")


if __name__ == "__main__":
    main()
