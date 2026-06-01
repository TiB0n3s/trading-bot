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


def _project_python_files() -> list[Path]:
    ignored_parts = {
        ".git",
        "__pycache__",
        "venv",
        ".pytest_cache",
    }
    return sorted(
        path
        for path in ROOT.rglob("*.py")
        if not any(part in ignored_parts for part in path.parts)
        and "tests" not in path.relative_to(ROOT).parts
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


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                parts = []
                current = func
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                calls.add(".".join(reversed(parts)))
    return calls


def _assert_no_import(directory: str, banned: set[str], label: str):
    violations = []
    for path in _python_files(directory):
        for module in _imports(path):
            root = module.split(".", 1)[0]
            if module in banned or root in banned:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert_true(not violations, f"{label}: {violations}")


APPROVED_DB_BOUNDARIES = {
    "db.py",
    "db_migrations.py",
}
APPROVED_DB_BOUNDARY_PREFIXES = {
    "repositories/",
    "migrations/",
}

TEMPORARY_REPORT_DB_ALLOWLIST = set()

TEMPORARY_BACKFILL_TRAINING_DB_ALLOWLIST = set()

TEMPORARY_DB_ACCESS_ALLOWLIST = (
    TEMPORARY_REPORT_DB_ALLOWLIST | TEMPORARY_BACKFILL_TRAINING_DB_ALLOWLIST
)

APPROVED_BROKER_BOUNDARIES = {
    "broker.py",
    "services/broker_service.py",
    "services/container.py",
    "services/fill_stream_service.py",
    "services/market_data_service.py",
}

TEMPORARY_BROKER_ACCESS_ALLOWLIST = set()

APPROVED_MARKET_DATA_BOUNDARIES = {
    "broker.py",
    "services/market_data_service.py",
    "services/execution_adapters.py",
    "services/momentum_service.py",
    "services/pre_market_research_service.py",
    "services/live_features_service.py",
    "services/label_features_market_data_service.py",
    "services/position_market_data_service.py",
    "services/rejected_signal_outcome_market_data_service.py",
    "services/rolling_momentum_service.py",
    "services/session_momentum_service.py",
    "services/excursion_service.py",
    "services/missed_opportunity_service.py",
    "services/strong_day_participation_service.py",
}

TEMPORARY_MARKET_DATA_ALLOWLIST_REASONS: dict[str, str] = {}
TEMPORARY_MARKET_DATA_ACCESS_ALLOWLIST = set(TEMPORARY_MARKET_DATA_ALLOWLIST_REASONS)


def _is_db_access(path: Path) -> bool:
    imports = _imports(path)
    calls = _calls(path)
    return (
        "sqlite3" in imports
        or "db" in imports
        or "get_connection" in calls
        or "sqlite3.connect" in calls
    )


def _is_broker_access(path: Path) -> bool:
    imports = _imports(path)
    return any(
        module == "broker"
        or module.startswith("broker.")
        or module == "alpaca_trade_api"
        or module.startswith("alpaca_trade_api.")
        for module in imports
    )


def _is_market_data_access(path: Path) -> bool:
    calls = _calls(path)
    return any(
        call.endswith(".get_bars")
        or call.endswith(".get_barset_with_fallback")
        or call.endswith(".get_bars_with_fallback")
        or call.endswith(".get_latest_trade")
        or call.endswith(".get_latest_quote")
        for call in calls
    )


def _assert_access_with_allowlist(
    predicate,
    approved: set[str],
    approved_prefixes: set[str],
    temporary: set[str],
    label: str,
) -> None:
    violations = []
    for path in _project_python_files():
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in approved_prefixes):
            continue
        if predicate(path) and rel not in approved and rel not in temporary:
            violations.append(rel)
    assert_true(not violations, f"{label} boundary violations: {violations}")


def _report_and_builder_files() -> list[Path]:
    patterns = ["*_report.py", "*_builder.py"]
    files = []
    for pattern in patterns:
        files.extend(ROOT.glob(pattern))
        files.extend((ROOT / "market_intelligence").glob(pattern))
        files.extend((ROOT / "ml_platform").glob(pattern))
    ops_check = ROOT / "ops_check.py"
    if ops_check.exists():
        files.append(ops_check)
    return sorted(set(path for path in files if "tests" not in path.parts))


def _runtime_python_files() -> list[Path]:
    runtime_paths = [
        "app.py",
        "services",
        "api",
        "position_manager.py",
        "auto_buy_manager.py",
        "portfolio_rotation_manager.py",
        "fill_stream.py",
        "fill_poller.py",
        "session_momentum.py",
        "live_features.py",
        "prediction_cache.py",
    ]
    files: list[Path] = []
    for item in runtime_paths:
        path = ROOT / item
        if path.is_dir():
            files.extend(_python_files(item))
        elif path.exists():
            files.append(path)
    return sorted(set(files))


def test_api_cannot_import_broker_directly():
    _assert_no_import("api", {"broker"}, "api broker boundary")


def test_app_cannot_import_sqlite3():
    imports = _imports(ROOT / "app.py")
    assert_true("sqlite3" not in imports, "app.py sqlite3 boundary")


def test_app_py_stays_under_1500_lines():
    line_count = (ROOT / "app.py").read_text().count("\n") + 1
    assert_true(line_count < 1500, f"app.py line count {line_count} < 1500")


def test_app_cannot_call_broker_directly():
    imports = _imports(ROOT / "app.py")
    calls = _calls(ROOT / "app.py")
    violations = []
    for module in imports:
        if module == "broker" or module.startswith("broker."):
            violations.append(f"imports {module}")
    for call in calls:
        if call.startswith("broker.") or call.startswith("api."):
            violations.append(f"calls {call}")
    assert_true(not violations, f"app.py broker boundary: {violations}")


def test_app_has_no_legacy_signal_or_direct_audit_execution_ownership():
    source = (ROOT / "app.py").read_text()
    banned_tokens = (
        "_legacy_process_signal",
        "legacy_process_signal",
        "execute_legacy",
        "run_legacy_",
        "def log_trade",
        "def log_rejection",
        "log_trade(",
        "log_rejection(",
        "execute_order(",
    )
    violations = [token for token in banned_tokens if token in source]
    assert_true(
        not violations,
        f"app.py must stay orchestration/composition-only; banned runtime ownership tokens: {violations}",
    )


def test_app_does_not_define_runtime_owner_classes():
    tree = ast.parse((ROOT / "app.py").read_text(), filename="app.py")
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    assert_true(
        not classes,
        f"app.py should stay composition-only and not define runtime owner classes: {classes}",
    )


def test_api_cannot_import_runtime_infra_directly():
    _assert_no_import(
        "api",
        {
            "broker",
            "repositories",
            "services.market_data_service",
            "services.broker_service",
        },
        "api runtime infra boundary",
    )


def test_repositories_cannot_import_flask():
    _assert_no_import("repositories", {"flask"}, "repository Flask boundary")


def test_repositories_cannot_import_broker():
    _assert_no_import(
        "repositories",
        {"broker", "alpaca_trade_api"},
        "repository broker boundary",
    )


def test_policies_cannot_import_routes():
    _assert_no_import("services/policies", {"api"}, "policy route boundary")


def test_policies_cannot_import_runtime_services():
    _assert_no_import(
        "services/policies",
        {"services.broker_service", "services.market_data_service"},
        "policy runtime service boundary",
    )


def test_live_signal_processor_cannot_import_flask():
    imports = _imports(ROOT / "services/live_signal_processor.py")
    assert_true("flask" not in imports, "live signal processor Flask boundary")


def test_direct_db_access_is_approved_or_tracked():
    _assert_access_with_allowlist(
        _is_db_access,
        APPROVED_DB_BOUNDARIES,
        APPROVED_DB_BOUNDARY_PREFIXES,
        TEMPORARY_DB_ACCESS_ALLOWLIST,
        "db access",
    )


def test_direct_broker_access_is_approved_or_tracked():
    _assert_access_with_allowlist(
        _is_broker_access,
        APPROVED_BROKER_BOUNDARIES,
        set(),
        TEMPORARY_BROKER_ACCESS_ALLOWLIST,
        "broker access",
    )


def test_market_data_access_is_approved_or_tracked():
    _assert_access_with_allowlist(
        _is_market_data_access,
        APPROVED_MARKET_DATA_BOUNDARIES,
        set(),
        TEMPORARY_MARKET_DATA_ACCESS_ALLOWLIST,
        "market-data access",
    )


def test_temporary_architecture_allowlists_are_empty():
    assert_true(
        TEMPORARY_REPORT_DB_ALLOWLIST == set(),
        "temporary report DB allowlist is empty",
    )
    assert_true(
        TEMPORARY_BACKFILL_TRAINING_DB_ALLOWLIST == set(),
        "temporary backfill/training DB allowlist is empty",
    )
    assert_true(
        TEMPORARY_DB_ACCESS_ALLOWLIST == set(),
        "temporary DB allowlist is empty",
    )
    assert_true(
        TEMPORARY_BROKER_ACCESS_ALLOWLIST == set(),
        "temporary broker allowlist is empty",
    )
    assert_true(
        TEMPORARY_MARKET_DATA_ALLOWLIST_REASONS == {},
        "temporary market-data allowlist reasons are empty",
    )
    assert_true(
        TEMPORARY_MARKET_DATA_ACCESS_ALLOWLIST == set(),
        "temporary market-data allowlist is empty",
    )


def test_temporary_market_data_allowlist_entries_have_todo_reasons():
    missing_reasons = []
    for rel, reason in TEMPORARY_MARKET_DATA_ALLOWLIST_REASONS.items():
        if not reason or "TODO" not in reason:
            missing_reasons.append(rel)
    assert_true(
        not missing_reasons,
        f"temporary market-data allowlist entries need TODO reasons: {missing_reasons}",
    )


def test_no_runtime_modules_have_direct_db_or_broker_access():
    approved_broker_runtime = APPROVED_BROKER_BOUNDARIES
    violations = []
    for path in _runtime_python_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("repositories/"):
            continue
        if _is_db_access(path):
            violations.append(f"{rel}: direct db access")
        if _is_broker_access(path) and rel not in approved_broker_runtime:
            violations.append(f"{rel}: direct broker access")
    assert_true(not violations, f"runtime direct DB/broker leaks: {violations}")


def test_reports_builders_and_ops_check_do_not_import_db_directly():
    violations = []
    banned_imports = {"db", "sqlite3"}
    for path in _report_and_builder_files():
        imports = _imports(path)
        calls = _calls(path)
        rel = path.relative_to(ROOT).as_posix()
        for module in imports:
            root = module.split(".", 1)[0]
            if module in banned_imports or root in banned_imports:
                violations.append(f"{rel} imports {module}")
        for call in calls:
            if call == "get_connection" or call == "sqlite3.connect":
                violations.append(f"{rel} calls {call}")
    assert_true(not violations, f"report/builder DB import boundary: {violations}")


def test_ops_checks_do_not_import_db_or_market_data_directly():
    violations = []
    banned_imports = {"db", "sqlite3", "broker", "alpaca_trade_api"}
    for path in _python_files("services/ops_checks"):
        imports = _imports(path)
        calls = _calls(path)
        rel = path.relative_to(ROOT).as_posix()
        for module in imports:
            root = module.split(".", 1)[0]
            if module in banned_imports or root in banned_imports:
                violations.append(f"{rel} imports {module}")
        for call in calls:
            if (
                call == "get_connection"
                or call == "sqlite3.connect"
                or call.endswith(".get_bars")
                or call.endswith(".get_bars_with_fallback")
                or call.endswith(".get_latest_quote")
                or call.endswith(".get_latest_trade")
            ):
                violations.append(f"{rel} calls {call}")
    assert_true(not violations, f"ops-check boundary violations: {violations}")


def main():
    tests = [
        test_api_cannot_import_broker_directly,
        test_app_cannot_import_sqlite3,
        test_app_py_stays_under_1500_lines,
        test_app_cannot_call_broker_directly,
        test_app_has_no_legacy_signal_or_direct_audit_execution_ownership,
        test_app_does_not_define_runtime_owner_classes,
        test_api_cannot_import_runtime_infra_directly,
        test_repositories_cannot_import_flask,
        test_repositories_cannot_import_broker,
        test_policies_cannot_import_routes,
        test_policies_cannot_import_runtime_services,
        test_live_signal_processor_cannot_import_flask,
        test_direct_db_access_is_approved_or_tracked,
        test_direct_broker_access_is_approved_or_tracked,
        test_market_data_access_is_approved_or_tracked,
        test_temporary_architecture_allowlists_are_empty,
        test_temporary_market_data_allowlist_entries_have_todo_reasons,
        test_no_runtime_modules_have_direct_db_or_broker_access,
        test_reports_builders_and_ops_check_do_not_import_db_directly,
        test_ops_checks_do_not_import_db_or_market_data_directly,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} architecture boundary tests passed.")


if __name__ == "__main__":
    main()
