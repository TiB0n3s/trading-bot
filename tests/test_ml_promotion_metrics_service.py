#!/usr/bin/env python3
"""Tests for measured ML promotion metrics."""
# ruff: noqa: E402

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

from ml_platform.lifecycle import REQUIRED_PROMOTION_METRICS
from services.ml_promotion_metrics_service import (
    PromotionMetricsConfig,
    build_ml_promotion_metrics_payload,
)


def _make_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                decision_time TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                final_decision TEXT,
                rejection_reason TEXT,
                account_state_json TEXT,
                prediction_score REAL,
                canonical_intelligence_json TEXT,
                canonical_intelligence_version TEXT,
                canonical_intelligence_hash TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO decision_snapshots (
                id, trade_id, decision_time, symbol, action, approved,
                final_decision, rejection_reason, account_state_json,
                prediction_score, canonical_intelligence_json,
                canonical_intelligence_version, canonical_intelligence_hash
            ) VALUES
              (1, 10, '2026-06-08T14:30:00+00:00', 'AAPL', 'buy', 1,
               'approved', NULL, '{}', 0.75, ?, 'canonical_intelligence_v1', ?),
              (2, 20, '2026-06-08T15:35:00+00:00', 'MSFT', 'buy', 0,
               'rejected', 'prediction_gate:test', '{}', 0.35, ?,
               'canonical_intelligence_v1', ?),
              (3, 30, '2026-06-08T19:10:00+00:00', 'NVDA', 'buy', 1,
               'approved', NULL, '{}', 0.25, ?, 'canonical_intelligence_v1', ?)
            """,
            (
                json.dumps(
                    {
                        "setup_state": {"label": "breakout"},
                        "regime_state": {"market_regime": "trend_expansion"},
                    }
                ),
                "a" * 64,
                json.dumps(
                    {
                        "setup_state": {"label": "late_chase"},
                        "regime_state": {"market_regime": "compression_chop"},
                    }
                ),
                "b" * 64,
                json.dumps(
                    {
                        "setup_state": {"label": "failed_breakout"},
                        "regime_state": {"market_regime": "trend_expansion"},
                    }
                ),
                "c" * 64,
            ),
        )
        con.execute(
            """
            CREATE TABLE exit_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_trade_id INTEGER,
                exit_timestamp TEXT,
                exit_trigger TEXT,
                exit_source TEXT,
                realized_pnl REAL,
                realized_return_pct REAL,
                mfe_pct REAL,
                capture_ratio REAL,
                max_adverse_excursion_pct REAL,
                avoided_drawdown_pct REAL,
                missed_upside_pct REAL,
                reentry_window_summary TEXT,
                canonical_exit_version TEXT,
                canonical_exit_hash TEXT,
                entry_canonical_intelligence_hash TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO exit_snapshots (
                entry_trade_id, exit_timestamp, exit_trigger, exit_source,
                realized_pnl, realized_return_pct, mfe_pct, capture_ratio,
                max_adverse_excursion_pct, avoided_drawdown_pct, missed_upside_pct,
                reentry_window_summary, canonical_exit_version, canonical_exit_hash,
                entry_canonical_intelligence_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    10,
                    "2026-06-08T15:20:00+00:00",
                    "peak_lock_floor",
                    "position_manager",
                    12.5,
                    0.8,
                    1.2,
                    0.67,
                    -0.2,
                    0.3,
                    0.1,
                    "no_clean_reentry_60m",
                    "canonical_exit_v1",
                    "x" * 64,
                    "a" * 64,
                ),
                (
                    30,
                    "2026-06-08T19:45:00+00:00",
                    "risk_stop",
                    "position_manager",
                    -8.0,
                    -0.5,
                    0.1,
                    0.0,
                    -0.7,
                    0.0,
                    0.0,
                    "failed_follow_through",
                    "canonical_exit_v1",
                    "y" * 64,
                    "c" * 64,
                ),
            ],
        )
        con.execute(
            """
            CREATE TABLE rejected_signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                decision_snapshot_id INTEGER,
                label_status TEXT,
                return_30m REAL,
                return_60m REAL,
                return_eod REAL,
                max_favorable_60m REAL,
                max_adverse_60m REAL,
                canonical_intelligence_hash TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO rejected_signal_outcomes (
                trade_id, decision_snapshot_id, label_status, return_30m,
                return_60m, return_eod, max_favorable_60m, max_adverse_60m,
                canonical_intelligence_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (20, 2, "labeled", 0.4, 0.6, 0.7, 0.9, -0.15, "b" * 64),
        )


def test_ml_promotion_metrics_are_measured_from_lifecycle_and_replay():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trades.db"
        _make_db(db_path)
        replay = {
            "snapshots_evaluated": 3,
            "changed_decision_count": 2,
            "changed_to_block": 1,
            "changed_to_allow": 1,
            "avoided_losers": 1,
            "missed_winners": 0,
            "recovered_missed_winners": 1,
            "introduced_losers": 0,
            "net_simulated_delta_pct": 1.2,
            "friction_assumptions": {"round_trip_friction_bps": 10.0},
        }
        with patch(
            "services.ml_promotion_metrics_service.replay_decisions_v1",
            return_value=replay,
        ):
            payload = build_ml_promotion_metrics_payload(
                PromotionMetricsConfig(
                    start_date="2026-06-08",
                    end_date="2026-06-08",
                    db_path=db_path,
                )
            )

        assert payload["outcome_rows"] == 3
        assert payload["metrics"]["false_positive_cost"] == 0.5
        assert payload["metrics"]["false_negative_opportunity_cost"] == 0.6
        assert payload["metrics"]["avoid_loser_precision"] == 1.0
        assert payload["metrics"]["avoid_loser_recall"] == 1.0
        assert payload["metrics"]["slippage_adjusted_decision_delta"] == 1.2
        assert payload["metrics"]["brier_score"] is not None
        assert payload["metrics"]["calibration_error"] is not None
        assert payload["metrics"]["capture_ratio_improvement"] == -0.165
        assert set(REQUIRED_PROMOTION_METRICS) - set(payload["metrics"]) == set()
        assert payload["ready_for_candidate_registration_metrics"] is False
        assert (
            payload["paper_authority_assessment"]["authority_recommendation"]
            == "risk_reduction_only_no_new_approval_authority"
        )


if __name__ == "__main__":
    test_ml_promotion_metrics_are_measured_from_lifecycle_and_replay()
    print("[OK] test_ml_promotion_metrics_are_measured_from_lifecycle_and_replay")
    print("\nAll 1 ML promotion metrics tests passed.")
