#!/usr/bin/env python3
"""Ensure emitted rejection categories are registered."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.rejection_categories import ALL_REJECTION_CATEGORIES

EMITTER_FILES = [
    ROOT / "src" / "trading_bot" / "web" / "runtime_compat.py",
    ROOT / "src" / "trading_bot" / "services" / "preflight_service.py",
    ROOT / "src" / "trading_bot" / "services" / "execution_service.py",
    ROOT / "src" / "trading_bot" / "signals" / "approval" / "service.py",
]


def assert_true(value, label):
    if not value:
        raise AssertionError(label)


def _literal_string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _emitted_categories(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    categories: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name == "log_rejection" and len(node.args) >= 3:
            category = _literal_string(node.args[2])
            if category:
                categories.add(category)

        if func_name in {"PreflightResult", "ExecutionOutcome", "ApprovalDecision"}:
            for kw in node.keywords:
                if kw.arg in {"rejection_category", "category"}:
                    category = _literal_string(kw.value)
                    if category:
                        categories.add(category)

        if func_name == "_reject_current_signal" and node.args:
            category = _literal_string(node.args[0])
            if category:
                categories.add(category)

    return categories


def test_all_emitted_categories_are_registered():
    emitted = set()
    for path in EMITTER_FILES:
        emitted.update(_emitted_categories(path))

    missing = sorted(emitted - ALL_REJECTION_CATEGORIES)
    assert_true(not missing, f"unregistered rejection categories: {missing}")


def test_registry_contains_current_characterization_categories():
    expected = {
        "ghost_sell",
        "market_hours",
        "circuit_breaker",
        "duplicate_webhook",
        "symbol_override",
        "cooldown",
        "churn_window",
        "churn_price",
        "daily_symbol_buy_limit",
        "session_trade_count",
        "exposure_cap",
        "macro_risk",
        "macro_position_limit",
        "trend_confirmation",
        "fundamental_score",
        "chase_prevention",
        "sell_profit_threshold",
        "sell_discipline",
        "second_look",
        "confidence_gate",
        "session_momentum_gate",
        "one_bar_confirmation_hold",
    }
    missing = sorted(expected - ALL_REJECTION_CATEGORIES)
    assert_true(not missing, f"missing characterization categories: {missing}")


def main():
    tests = [
        test_all_emitted_categories_are_registered,
        test_registry_contains_current_characterization_categories,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} rejection category registry tests passed.")


if __name__ == "__main__":
    main()
