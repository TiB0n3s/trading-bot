#!/usr/bin/env python3
"""Tests for recurring after-close quant learning pipeline wiring."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import after_close_learning


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
    assert "candidate_outcome_backfill" in out
    assert "research_export" in out
    assert "paper_learning_authority" in out
    assert "automated_retraining" in out
    assert "point_in_time_archive" in out
    assert "pipeline.retrain" in out


if __name__ == "__main__":
    test_after_close_learning_dry_run_lists_recurring_quant_steps()
    print("after-close learning pipeline tests passed")
