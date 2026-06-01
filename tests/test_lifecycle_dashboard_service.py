#!/usr/bin/env python3
"""Tests for decision lifecycle dashboard summaries."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.lifecycle_dashboard_service import build_lifecycle_dashboard_payload


def test_lifecycle_dashboard_summarizes_full_path_and_missed_rejections():
    payload = build_lifecycle_dashboard_payload(
        [
            {
                "decision_time": "2026-06-01T10:00:00+00:00",
                "symbol": "AAPL",
                "action": "buy",
                "approved": 1,
                "final_decision": "approved",
                "lifecycle_status": "approved_with_exit",
                "exit_snapshot_id": 1,
                "exit_trigger": "target",
                "realized_return_pct": 0.8,
            },
            {
                "decision_time": "2026-06-01T10:05:00+00:00",
                "symbol": "MSFT",
                "action": "buy",
                "approved": 0,
                "final_decision": "rejected",
                "lifecycle_status": "rejected_with_counterfactual",
                "rejection_reason": "trend_confirmation",
                "rejected_return_60m": 0.2,
                "rejected_max_favorable_60m": 1.1,
                "setup_label": "breakout",
                "market_regime": "trend_expansion",
                "session_phase": "morning",
            },
        ]
    )

    assert payload.summary["report_version"] == "lifecycle_dashboard_v1"
    assert payload.summary["approved_rows"] == 1
    assert payload.summary["rejected_rows"] == 1
    assert payload.summary["analysis_ready"] is True
    assert payload.exit_trigger_counts[0]["bucket"] == "target"
    assert payload.top_missed_rejections[0]["symbol"] == "MSFT"


def main():
    tests = [test_lifecycle_dashboard_summarizes_full_path_and_missed_rejections]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} lifecycle dashboard tests passed.")


if __name__ == "__main__":
    main()
