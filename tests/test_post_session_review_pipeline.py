#!/usr/bin/env python3
"""Tests for post-session review pipeline wiring."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import post_session_review


def test_post_session_review_dry_run_lists_warn_only_review_steps():
    old_argv = sys.argv[:]
    try:
        sys.argv = [
            "pipeline/post_session_review.py",
            "--date",
            "2026-06-04",
            "--dry-run",
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = post_session_review.main()
    finally:
        sys.argv = old_argv

    out = buf.getvalue()
    assert code == 0
    assert "Post-session review pipeline" in out
    assert "post_session_operational_check" in out
    assert "rejected_signal_outcome_builder" in out
    assert "decision_lifecycle_dashboard" in out
    assert "automated_retraining" in out
    assert "bar_timing_quality_report" in out
    assert "learning_artifacts" in out
    assert "[CRITICAL]" not in out


def test_post_session_wrapper_delegates_to_pipeline_only():
    wrapper = (ROOT / "run_post_session_review.sh").read_text()

    assert "pipeline/post_session_review.py" in wrapper

    legacy_direct_calls = (
        "ops_check.py post",
        "rejected_signal_outcome_builder.py",
        "strong_day_participation_report.py",
        "tradingview_alert_coverage_report.py",
        "build_historical_trend_context.py",
        "predict_symbol_outcomes.py",
        "pipeline/retrain.py",
        "auto_buy_outcome_report.py",
        "entry_quality_report.py",
        "analytics_report.py",
        "filter_report.py",
    )
    offenders = [call for call in legacy_direct_calls if call in wrapper]
    assert not offenders, offenders


if __name__ == "__main__":
    test_post_session_review_dry_run_lists_warn_only_review_steps()
    test_post_session_wrapper_delegates_to_pipeline_only()
    print("post-session review pipeline tests passed")
