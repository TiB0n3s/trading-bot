"""
Focused tests for sell-side layered ML influence in position momentum monitor.

Run:
  python3 tests/test_position_momentum_monitor_ml.py
"""
# ruff: noqa: E402

import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from repositories import auto_sell_repo, position_momentum_repo
from trading_bot.ops_checks.commands.auto_sell_checks import run_auto_sell_health
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


def test_auto_sell_repo_persists_learning_candidate_and_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        auto_sell_repo.insert_candidate_and_snapshot(
            timestamp="2026-06-11 12:00:00",
            created_at="2026-06-11T12:00:01-05:00",
            position=Position(symbol="AAPL", qty=4, unrealized_plpc=-0.012),
            session={
                "trend_label": "fading",
                "trend_score": -3,
                "session_return_pct": -0.4,
                "momentum_5m_pct": -0.2,
                "distance_from_vwap_pct": -0.6,
            },
            decision={
                "symbol": "AAPL",
                "action": "sell_candidate",
                "severity": "layered_ml_exit",
                "reason": "test auto-sell learning",
                "sell_pressure_score": 8,
                "sell_pressure_recommendation": "full_exit",
                "sell_pressure_reason": "pressure test",
                "layered_ml_available": True,
                "layered_ml_final_instruction": "pass",
                "layered_ml_master_confidence_score": 82.0,
                "layered_ml_ensemble_probability_pct": 84.0,
                "layered_ml_reason": "test layered",
            },
            auto_sell_enabled=True,
            order={"order_id": "sell-1", "status": "submitted"},
            candidate_json='{"layered_ml_available": true}',
            order_json='{"order_id": "sell-1"}',
            db_path=db_path,
        )

        actions = auto_sell_repo.candidate_action_rows("2026-06-11", db_path=db_path)
        snapshots = auto_sell_repo.decision_snapshot_summary(
            "2026-06-11",
            db_path=db_path,
        )
        layered = auto_sell_repo.layered_ml_summary("2026-06-11", db_path=db_path)

    assert_equal(actions[0]["action"], "sell_candidate", "action")
    assert_equal(actions[0]["submitted"], 1, "submitted")
    assert_equal(snapshots["n"], 1, "snapshot rows")
    assert_equal(snapshots["submitted"], 1, "snapshot submitted")
    assert_equal(snapshots["layered_rows"], 1, "snapshot layered")
    assert_equal(layered[0]["instruction"], "pass", "layered instruction")
    assert_equal(layered[0]["sell_candidates"], 1, "layered sell candidates")


def test_log_position_momentum_check_emits_auto_sell_learning_snapshot():
    captured = {}
    old_insert_check = position_momentum_repo.insert_check
    old_insert_auto_sell = auto_sell_repo.insert_candidate_and_snapshot

    def fake_insert_check(**kwargs):
        captured["position_check"] = kwargs

    def fake_insert_auto_sell(**kwargs):
        captured["auto_sell"] = kwargs

    position_momentum_repo.insert_check = fake_insert_check
    auto_sell_repo.insert_candidate_and_snapshot = fake_insert_auto_sell
    try:
        monitor.log_position_momentum_check(
            position=Position(symbol="AAPL", qty=2),
            session={"trend_label": "fading"},
            decision={
                "symbol": "AAPL",
                "action": "sell_candidate",
                "severity": "layered_ml_exit",
                "reason": "test",
                "layered_ml_available": True,
                "layered_ml_final_instruction": "pass",
                "layered_ml_master_confidence_score": 81.0,
            },
            auto_sell_enabled=True,
            order={"order_id": "sell-2", "status": "submitted"},
        )
    finally:
        position_momentum_repo.insert_check = old_insert_check
        auto_sell_repo.insert_candidate_and_snapshot = old_insert_auto_sell

    assert_equal(
        captured["position_check"]["timestamp"],
        captured["auto_sell"]["timestamp"],
        "shared timestamp",
    )
    assert_equal(captured["auto_sell"]["position"].symbol, "AAPL", "symbol")
    assert_equal(captured["auto_sell"]["auto_sell_enabled"], True, "enabled")
    if '"layered_ml_available": true' not in captured["auto_sell"]["candidate_json"]:
        raise AssertionError("auto-sell candidate snapshot did not include layered ML evidence")


def test_auto_sell_health_report_reads_first_class_learning_tables():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        db_path = base_dir / "trades.db"
        auto_sell_repo.insert_candidate_and_snapshot(
            timestamp="2026-06-11 12:00:00",
            created_at="2026-06-11T12:00:01-05:00",
            position=Position(symbol="AAPL", qty=4, unrealized_plpc=-0.012),
            session={"trend_label": "fading", "trend_score": -3},
            decision={
                "symbol": "AAPL",
                "action": "sell_candidate",
                "severity": "layered_ml_exit",
                "reason": "test auto-sell learning",
                "sell_pressure_score": 8,
                "layered_ml_available": True,
                "layered_ml_final_instruction": "pass",
                "layered_ml_master_confidence_score": 82.0,
                "layered_ml_ensemble_probability_pct": 84.0,
                "layered_ml_reason": "test layered",
            },
            auto_sell_enabled=True,
            order={"order_id": "sell-1", "status": "submitted"},
            candidate_json='{"layered_ml_available": true}',
            order_json='{"order_id": "sell-1"}',
            db_path=db_path,
        )

        output = StringIO()
        with redirect_stdout(output):
            ok = run_auto_sell_health("2026-06-11", base_dir=base_dir)

    text = output.getvalue()
    assert_equal(ok, True, "auto-sell report status")
    for expected in (
        "Auto-Sell Candidates",
        "Layered ML influence",
        "Top auto-sell candidates",
        "AAPL",
    ):
        if expected not in text:
            raise AssertionError(f"missing expected report text: {expected}")


def main():
    tests = [
        test_layered_ml_promotes_loss_watch_to_sell_candidate,
        test_layered_ml_downgrades_weak_nonprotective_sell_candidate,
        test_layered_ml_does_not_downgrade_protective_emergency_exit,
        test_position_momentum_repo_persists_layered_ml_evidence,
        test_auto_sell_repo_persists_learning_candidate_and_snapshot,
        test_log_position_momentum_check_emits_auto_sell_learning_snapshot,
        test_auto_sell_health_report_reads_first_class_learning_tables,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print()
    print(f"All {len(tests)} position momentum layered ML tests passed.")


if __name__ == "__main__":
    main()
