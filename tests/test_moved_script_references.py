#!/usr/bin/env python3
"""Regression checks for scripts moved out of the repo root."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_run_tests_module():
    script = ROOT / "scripts" / "run_tests.py"
    spec = importlib.util.spec_from_file_location("tradingbot_run_tests", script)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_tests_resolves_repo_root_after_move():
    module = _load_run_tests_module()

    assert module.ROOT == ROOT
    assert (module.ROOT / "tests").is_dir()
    assert (module.ROOT / "scripts" / "run_tests.py").is_file()


def test_run_tests_listed_files_exist_from_repo_root():
    module = _load_run_tests_module()

    missing = [path for path in module.TESTS if not (module.ROOT / path).is_file()]

    assert not missing


def test_run_tests_child_env_exposes_repo_and_scripts_paths():
    module = _load_run_tests_module()

    paths = module.child_test_env()["PYTHONPATH"].split(module.os.pathsep)

    assert paths[0] == str(ROOT)
    assert paths[1] == str(ROOT / "scripts")
    assert paths[2] == str(ROOT / "src")


def test_fast_safety_runner_exposes_src_path_for_raw_local_execution():
    safety_runner = (ROOT / "run_safety_checks.py").read_text()

    assert 'str(ROOT / "src")' in safety_runner


def test_container_and_systemd_references_use_scripts_paths():
    dockerfile = (ROOT / "Dockerfile").read_text()
    live_bar_unit = (ROOT / "ops" / "live-bar-stream.service").read_text()

    assert '["python", "scripts/run_tests.py"]' in dockerfile
    assert "/trading-bot/scripts/live_bar_stream.py" in live_bar_unit
    assert "/trading-bot/live_bar_stream.py" not in live_bar_unit


def test_moved_fill_stream_script_bootstraps_repo_import_paths():
    script = ROOT / "scripts" / "fill_stream.py"
    source = script.read_text()

    assert 'ROOT / "scripts"' in source
    assert 'ROOT / "src"' in source
    assert 'logging.FileHandler(ROOT / "fill_stream.log")' in source
    assert "from services.container import ApplicationContainer" in source
    assert "from services.fill_stream_service import FillStreamService" in source


def test_repo_safety_scripts_cover_active_source_dirs():
    safe_repo_check = (ROOT / "safe_repo_check.sh").read_text()
    source_snapshot = (ROOT / "source_snapshot.sh").read_text()
    expected_dirs = (
        "api",
        "config",
        "dashboards",
        "ml",
        "ml_platform",
        "ops",
        "pipeline",
        "reports",
        "repositories",
        "scripts",
        "services",
        "src",
    )

    for directory in expected_dirs:
        assert f"\n  {directory} \\\n" in source_snapshot

    source_dirs = tuple(directory for directory in expected_dirs if directory != "ml")
    for directory in source_dirs:
        assert f"\n  {directory}\n" in safe_repo_check


def test_ci_uses_pinned_dev_requirements():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "python -m pip install -r requirements-dev.txt" in ci
    assert "python -m pip install pytest ruff" not in ci


def test_ops_check_allows_skipping_default_venv_reexec_for_adapter_venvs():
    source = (ROOT / "src" / "trading_bot" / "ops_checks" / "legacy_cli.py").read_text()

    assert "TRADING_BOT_SKIP_VENV_REEXEC" in source


def main():
    tests = [
        test_run_tests_resolves_repo_root_after_move,
        test_run_tests_listed_files_exist_from_repo_root,
        test_run_tests_child_env_exposes_repo_and_scripts_paths,
        test_fast_safety_runner_exposes_src_path_for_raw_local_execution,
        test_container_and_systemd_references_use_scripts_paths,
        test_moved_fill_stream_script_bootstraps_repo_import_paths,
        test_repo_safety_scripts_cover_active_source_dirs,
        test_ci_uses_pinned_dev_requirements,
        test_ops_check_allows_skipping_default_venv_reexec_for_adapter_venvs,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} moved script reference tests passed.")


if __name__ == "__main__":
    main()
