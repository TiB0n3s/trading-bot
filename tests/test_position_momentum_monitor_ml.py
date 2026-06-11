"""
Focused tests for sell-side layered ML influence in position momentum monitor.

Run:
  python3 tests/test_position_momentum_monitor_ml.py
"""
# ruff: noqa: E402

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from repositories import position_momentum_repo
from trading_bot.signals.auto_sell import manager as monitor


class Position:
    def __init__(self, symbol="AAPL", qty=5, unrealized_plpc=-0.01):
        self.symbol = symbol
        self.qty = qty
        self.unrealized_pl = -50.0
        self.unrealized_plpc = unrealized_plpc


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def _layered(master=80.0, ensemble=82.0):
    return {
        "enabled": True,
        "available": True,
        "runtime_effect": "paper_bounded_position_momentum_intelligence_authority",
        "final_instruction": "pass",
        "final_size_pct": 1.0,
        "ensemble_probability_pct": ensemble,
        "master_confidence_score": master,
        "paper_recommendation": "paper_trade_candidate",
        "reason": "test layered sell context",
        "decision": {"final_instruction": "pass"},
        "historical_bar_paper_strategy": {"master_confidence_score": master},
        "bar_pattern_features": {"symbol": "AAPL"},
    }


def test_layered_ml_promotes_loss_watch_to_sell_candidate():
    old_context = monitor.build_position_layered_ml_context
    old_enabled = monitor.POSITION_MOMENTUM_LAYERED_ML_ENABLED
    monitor.POSITION_MOMENTUM_LAYERED_ML_ENABLED = True
    monitor.build_position_layered_ml_context = lambda **kwargs: _layered()
    try:
        decision = monitor.apply_layered_ml_to_sell_decision(
            position=Position(unrealized_plpc=-0.012),
            session={"trend_label": "fading"},
            decision={
                "symbol": "AAPL",
                "action": "watch",
                "severity": "soft_negative",
                "score": -3,
                "sell_pressure_score": 6,
                "reason": "soft negative",
            },
        )
    finally:
        monitor.build_position_layered_ml_context = old_context
        monitor.POSITION_MOMENTUM_LAYERED_ML_ENABLED = old_enabled

    assert_equal(decision["action"], "sell_candidate", "action")
    assert_equal(decision["severity"], "layered_ml_exit", "severity")
    assert_equal(decision["layered_ml_master_confidence_score"], 80.0, "confidence")


def test_layered_ml_downgrades_weak_nonprotective_sell_candidate():
    old_context = monitor.build_position_layered_ml_context
    old_enabled = monitor.POSITION_MOMENTUM_LAYERED_ML_ENABLED
    monitor.POSITION_MOMENTUM_LAYERED_ML_ENABLED = True
    monitor.build_position_layered_ml_context = lambda **kwargs: _layered(
        master=35.0, ensemble=40.0
    )
    try:
        decision = monitor.apply_layered_ml_to_sell_decision(
            position=Position(unrealized_plpc=-0.002),
            session={"trend_label": "rangebound"},
            decision={
                "symbol": "AAPL",
                "action": "sell_candidate",
                "severity": "soft_negative",
                "score": -2,
                "sell_pressure_score": 4,
                "reason": "weak sell candidate",
            },
        )
    finally:
        monitor.build_position_layered_ml_context = old_context
        monitor.POSITION_MOMENTUM_LAYERED_ML_ENABLED = old_enabled

    assert_equal(decision["action"], "watch", "action")
    assert_equal(decision["severity"], "layered_ml_exit_caution", "severity")


def test_layered_ml_does_not_downgrade_protective_emergency_exit():
    old_context = monitor.build_position_layered_ml_context
    old_enabled = monitor.POSITION_MOMENTUM_LAYERED_ML_ENABLED
    monitor.POSITION_MOMENTUM_LAYERED_ML_ENABLED = True
    monitor.build_position_layered_ml_context = lambda **kwargs: _layered(
        master=30.0, ensemble=35.0
    )
    try:
        decision = monitor.apply_layered_ml_to_sell_decision(
            position=Position(unrealized_plpc=-0.02),
            session={"trend_label": "downtrend"},
            decision={
                "symbol": "AAPL",
                "action": "sell_candidate",
                "severity": "emergency_loss",
                "score": -6,
                "sell_pressure_score": 8,
                "reason": "emergency loss",
            },
        )
    finally:
        monitor.build_position_layered_ml_context = old_context
        monitor.POSITION_MOMENTUM_LAYERED_ML_ENABLED = old_enabled

    assert_equal(decision["action"], "sell_candidate", "action")
    assert_equal(decision["severity"], "emergency_loss", "severity")


def test_position_momentum_repo_persists_layered_ml_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        position_momentum_repo.init_checks_table(db_path)
        position_momentum_repo.insert_check(
            timestamp="2026-06-11 12:00:00",
            symbol="AAPL",
            qty=3,
            action="sell_candidate",
            severity="layered_ml_exit",
            reason="test",
            session={"trend_label": "fading"},
            unrealized_pl=-10.0,
            unrealized_plpc=-1.0,
            auto_sell_enabled=True,
            order_submitted=False,
            order_id=None,
            sell_pressure_score=6,
            sell_pressure_recommendation="watch",
            sell_pressure_reason="test pressure",
            layered_ml_available=True,
            layered_ml_final_instruction="pass",
            layered_ml_master_confidence_score=81.0,
            layered_ml_ensemble_probability_pct=83.0,
            layered_ml_reason="test layered",
            layered_ml_json='{"ok": true}',
            db_path=db_path,
        )
        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                """
                SELECT layered_ml_available,
                       layered_ml_final_instruction,
                       layered_ml_master_confidence_score,
                       layered_ml_ensemble_probability_pct,
                       layered_ml_reason,
                       layered_ml_json
                FROM position_momentum_checks
                LIMIT 1
                """
            ).fetchone()
    assert_equal(row["layered_ml_available"], 1, "available")
    assert_equal(row["layered_ml_final_instruction"], "pass", "instruction")
    assert_equal(row["layered_ml_master_confidence_score"], 81.0, "master")
    assert_equal(row["layered_ml_ensemble_probability_pct"], 83.0, "ensemble")
    assert_equal(row["layered_ml_reason"], "test layered", "reason")
    assert_equal(row["layered_ml_json"], '{"ok": true}', "json")


def main():
    tests = [
        test_layered_ml_promotes_loss_watch_to_sell_candidate,
        test_layered_ml_downgrades_weak_nonprotective_sell_candidate,
        test_layered_ml_does_not_downgrade_protective_emergency_exit,
        test_position_momentum_repo_persists_layered_ml_evidence,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print()
    print(f"All {len(tests)} position momentum layered ML tests passed.")


if __name__ == "__main__":
    main()
