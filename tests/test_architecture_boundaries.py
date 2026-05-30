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


APPROVED_DB_ACCESS = {
    "db.py",
    "db_migrations.py",
}

TEMPORARY_DB_ACCESS_ALLOWLIST = {
    "adaptive_impact_report.py",
    "analytics_ext/attribution.py",
    "analytics_ext/replay_engine.py",
    "analytics_report.py",
    "app.py",
    "auto_buy_manager.py",
    "auto_buy_outcome_report.py",
    "backfill_missing_fills.py",
    "backfill_setup_labels.py",
    "blocked_signal_outcome_report.py",
    "bot_events.py",
    "build_historical_trend_context.py",
    "buy_opportunity_report.py",
    "collect_and_score_events.py",
    "context_trade_join_report.py",
    "daily_summary.py",
    "data_layer/ledger.py",
    "decision_engine.py",
    "decision_snapshots.py",
    "drawdown_report.py",
    "entry_quality_report.py",
    "event_attribution_report.py",
    "excursion_report.py",
    "export_ml_dataset.py",
    "fill_poller.py",
    "fill_stream.py",
    "filter_report.py",
    "ingest_market_context.py",
    "init_prediction_db.py",
    "intelligence_context_report.py",
    "intelligence_learning_report.py",
    "intelligence_prediction_report.py",
    "label_features.py",
    "label_v1_builder.py",
    "live_features.py",
    "live_score_monitor.py",
    "market_alignment_report.py",
    "market_intelligence/experience_model.py",
    "market_intelligence/intelligence_store.py",
    "missed_opportunity_report.py",
    "ml_platform/brain_features.py",
    "ml_platform/cli.py",
    "ml_platform/dataset_builder.py",
    "ml_platform/datasets.py",
    "ml_platform/governance.py",
    "ml_platform/replay.py",
    "ml_platform/serving.py",
    "ml_platform/staged.py",
    "ml_platform/validation.py",
    "ops_check.py",
    "pnl.py",
    "policy_backtest.py",
    "portfolio_replacement_report.py",
    "portfolio_rotation_manager.py",
    "portfolio_state.py",
    "position_manager.py",
    "position_momentum_monitor.py",
    "post_session_check.py",
    "pre_market_research_data.py",
    "prediction_cache.py",
    "prediction_report.py",
    "prediction_validation_report.py",
    "prior_session_context.py",
    "rejected_signal_outcome_builder.py",
    "session_gate_report.py",
    "session_momentum.py",
    "setup_engine.py",
    "signal_event_builder.py",
    "signal_outcome_builder.py",
    "signal_timing_lesson_report.py",
    "strategy_intelligence_report.py",
    "strategy_learner.py",
    "strong_day_participation_report.py",
    "trade_matcher.py",
    "tradingview_alert_coverage_report.py",
    "trend_context_report.py",
}

APPROVED_BROKER_ACCESS = {
    "broker.py",
    "services/broker_service.py",
    "services/container.py",
}

TEMPORARY_BROKER_ACCESS_ALLOWLIST = {
    "fill_stream.py",
    "morning_check.py",
    "services/market_data_service.py",
}

APPROVED_MARKET_DATA_ACCESS = {
    "services/market_data_service.py",
    "services/momentum_service.py",
    "live_features.py",
}

TEMPORARY_MARKET_DATA_ACCESS_ALLOWLIST = {
    "app.py",
    "broker.py",
    "excursion_report.py",
    "label_features.py",
    "missed_opportunity_report.py",
    "position_manager.py",
    "pre_market_research_data.py",
    "rejected_signal_outcome_builder.py",
    "rolling_momentum.py",
    "session_momentum.py",
    "services/policies/entry_policy.py",
    "services/policies/execution_policy.py",
    "strong_day_participation_report.py",
}


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
    temporary: set[str],
    label: str,
) -> None:
    violations = []
    for path in _project_python_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("repositories/") and label == "db access":
            continue
        if rel.startswith("migrations/") and label == "db access":
            continue
        if predicate(path) and rel not in approved and rel not in temporary:
            violations.append(rel)
    assert_true(not violations, f"{label} boundary violations: {violations}")


def test_api_cannot_import_broker_directly():
    _assert_no_import("api", {"broker"}, "api broker boundary")


def test_app_cannot_import_sqlite3():
    imports = _imports(ROOT / "app.py")
    assert_true("sqlite3" not in imports, "app.py sqlite3 boundary")


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
        APPROVED_DB_ACCESS,
        TEMPORARY_DB_ACCESS_ALLOWLIST,
        "db access",
    )


def test_direct_broker_access_is_approved_or_tracked():
    _assert_access_with_allowlist(
        _is_broker_access,
        APPROVED_BROKER_ACCESS,
        TEMPORARY_BROKER_ACCESS_ALLOWLIST,
        "broker access",
    )


def test_market_data_access_is_approved_or_tracked():
    _assert_access_with_allowlist(
        _is_market_data_access,
        APPROVED_MARKET_DATA_ACCESS,
        TEMPORARY_MARKET_DATA_ACCESS_ALLOWLIST,
        "market-data access",
    )


def main():
    tests = [
        test_api_cannot_import_broker_directly,
        test_app_cannot_import_sqlite3,
        test_app_cannot_call_broker_directly,
        test_api_cannot_import_runtime_infra_directly,
        test_repositories_cannot_import_flask,
        test_repositories_cannot_import_broker,
        test_policies_cannot_import_routes,
        test_policies_cannot_import_runtime_services,
        test_live_signal_processor_cannot_import_flask,
        test_direct_db_access_is_approved_or_tracked,
        test_direct_broker_access_is_approved_or_tracked,
        test_market_data_access_is_approved_or_tracked,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} architecture boundary tests passed.")


if __name__ == "__main__":
    main()
