#!/usr/bin/env python3
"""Tests for recurring after-close quant learning pipeline wiring."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import after_close_learning  # noqa: E402


def test_after_close_learning_dry_run_lists_recurring_quant_steps():
    old_argv = sys.argv[:]
    try:
        sys.argv = [
            "pipeline/after_close_learning.py",
            "--date",
            "2026-06-03",
            "--dry-run",
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = after_close_learning.main()
    finally:
        sys.argv = old_argv

    out = buf.getvalue()
    assert code == 0
    assert "After-close quant learning pipeline" in out
    assert "learning_backfill_repair" in out
    assert "pipeline.learning_backfill_repair" in out
    assert "excursion_memory" in out
    assert "missed_opportunity_memory" in out
    assert "symbol_momentum_timing_memory" in out
    assert "policy_backtest_summary" in out
    assert "portfolio_replacement_memory" in out
    assert "strategy_memory_refresh" in out
    assert "research_export" in out
    assert "paper_learning_authority" in out
    assert "historical_bar_completion_training" in out
    assert "historical_bar_paper_strategy_spy" in out
    assert "symbol_universe_retraining" in out
    assert "automated_retraining" in out
    assert "policy_artifact_register" in out
    assert "point_in_time_archive" in out
    assert "pipeline.retrain" in out
    assert "pipeline.historical_bar_completion_hook" in out
    assert "pipeline.symbol_universe_retrain" in out


def test_after_close_wrapper_delegates_learning_to_pipeline_only():
    wrapper = (ROOT / "run_after_close_learning.sh").read_text()

    assert "pipeline/after_close_learning.py" in wrapper

    legacy_direct_calls = (
        "python3 trade_matcher.py",
        "python3 strategy_learner.py",
        "python3 excursion_report.py",
        "python3 missed_opportunity_report.py",
        "python3 symbol_momentum_timing_report.py",
        "python3 policy_backtest.py",
        "python3 portfolio_replacement_report.py",
        "python3 strategy_brain_report.py",
        "python3 policy_artifacts.py register",
        "python3 archive_context_state.py",
    )
    offenders = [call for call in legacy_direct_calls if call in wrapper]
    assert not offenders, offenders


if __name__ == "__main__":
    test_after_close_learning_dry_run_lists_recurring_quant_steps()
    test_after_close_wrapper_delegates_learning_to_pipeline_only()
    print("after-close learning pipeline tests passed")
