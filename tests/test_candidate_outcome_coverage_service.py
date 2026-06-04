#!/usr/bin/env python3
"""Tests for shared candidate forward-outcome coverage semantics."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.candidate_outcome_coverage_service import (
    candidate_has_forward_outcome,
    summarize_candidate_outcome_coverage,
)


def test_candidate_has_forward_outcome_accepts_return_or_excursion_fields():
    assert candidate_has_forward_outcome({"forward_return_pct": 0.2}) is True
    assert candidate_has_forward_outcome({"max_favorable_60m": 1.1}) is True
    assert candidate_has_forward_outcome({"return_eod": -0.3}) is True
    assert candidate_has_forward_outcome({"score": 70}) is False


def test_candidate_outcome_coverage_splits_non_taken_learning_rows():
    summary = summarize_candidate_outcome_coverage(
        [
            {
                "candidate_status": "taken",
                "decision": "approved",
                "candidate_json": json.dumps({"forward_return_pct": 0.5}),
            },
            {
                "candidate_status": "near_threshold",
                "decision": "watch",
                "candidate_json": json.dumps({"forward_mfe_pct": 1.2}),
            },
            {
                "candidate_status": "scored_not_taken",
                "decision": "skip",
                "candidate_json": "{}",
            },
        ]
    )

    assert summary["rows"] == 3
    assert summary["rows_with_forward_outcome"] == 2
    assert summary["missing_forward_outcome"] == 1
    assert summary["forward_outcome_coverage_rate"] == 0.6667
    assert summary["non_taken_rows"] == 2
    assert summary["non_taken_with_forward_outcome"] == 1
    assert summary["non_taken_forward_outcome_coverage_rate"] == 0.5


if __name__ == "__main__":
    test_candidate_has_forward_outcome_accepts_return_or_excursion_fields()
    test_candidate_outcome_coverage_splits_non_taken_learning_rows()
    print("candidate outcome coverage service tests passed")
