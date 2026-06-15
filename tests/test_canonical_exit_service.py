#!/usr/bin/env python3
"""Tests for canonical exit snapshot construction and persistence."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.exit_snapshot_repo import ExitSnapshotRepository
from services.canonical_exit_service import (
    CANONICAL_EXIT_MAX_JSON_BYTES,
    CANONICAL_EXIT_REQUIRED_SECTIONS,
    CANONICAL_EXIT_VERSION,
    build_canonical_exit_snapshot,
    canonical_exit_json_size_bytes,
    validate_canonical_exit_snapshot_contract,
)
from services.exit_snapshot_service import (
    EXIT_POLICY_VERSION,
    POSITION_MANAGER_VERSION,
    REALIZED_EXIT_LABEL_VERSION,
    ExitSnapshotService,
)


def _canonical_intelligence(**overrides):
    data = {
        "version": "canonical_intelligence_v1",
        "feature_vector_hash": "a" * 64,
        "feature_semantic_version": "decision_snapshot_features_v2",
        "decision_ts": "2026-05-31T14:30:00+00:00",
        "regime_state": {"macro_regime": "risk_on"},
        "momentum_state": {"session_label": "strong_uptrend", "momentum_pct": 0.3},
        "trend_state": {"direction": "bullish", "strength": "confirmed"},
        "prediction_state": {"ml_bucket": "high_55_plus", "ml_score": 62},
        "setup_state": {"policy_action": "boost"},
        "source_timestamps": {"session_momentum_updated_at": "2026-05-31T14:29:00+00:00"},
        "freshness_sec": {"session_momentum": 60},
        "confidence": {"prediction_confidence": "medium"},
    }
    data.update(overrides)
    return data


def _snapshot(**overrides):
    args = {
        "symbol": "MSFT",
        "exit_ts": "2026-05-31T15:15:00+00:00",
        "exit_trigger": "peak_lock_floor",
        "exit_source": "position_manager",
        "decision_snapshot_id": 303,
        "entry_trade_id": 99,
        "exit_trade_id": 101,
        "matched_trade_id": 202,
        "position_id": "MSFT:99",
        "exit_order_id": "sell-1",
        "entry_canonical_intelligence_version": "canonical_intelligence_v1",
        "entry_canonical_intelligence_hash": "b" * 64,
        "canonical_intelligence": _canonical_intelligence(),
        "realized_outcome": {
            "realized_pnl": 12.5,
            "realized_return_pct": 0.42,
            "mfe_pct": 0.8,
            "capture_ratio": 0.525,
            "max_adverse_excursion_pct": -0.35,
        },
        "foregone_outcome": {
            "avoided_drawdown_pct": 0.3,
            "missed_upside_pct": 0.1,
        },
        "post_exit_path": {
            "return_30m_pct": -0.2,
            "return_60m_pct": -0.35,
            "reentry_window_summary": "no_clean_reentry_60m",
            "summary": "faded_after_exit",
        },
        "trigger_metadata": {"floor_pct": 0.25, "peak_pct": 0.8},
        "created_at": "2026-05-31T15:15:05+00:00",
    }
    args.update(overrides)
    return build_canonical_exit_snapshot(**args)


def _rows(db_path: Path):
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute("SELECT * FROM exit_snapshots ORDER BY id")]


def test_build_canonical_exit_snapshot_collects_exit_state_and_hashes():
    snapshot = _snapshot()
    data = snapshot.to_dict()

    assert data["version"] == CANONICAL_EXIT_VERSION
    assert data["symbol"] == "MSFT"
    assert data["exit_identity"]["exit_trade_id"] == 101
    assert data["exit_identity"]["decision_snapshot_id"] == 303
    assert data["exit_identity"]["entry_trade_id"] == 99
    assert data["exit_identity"]["position_id"] == "MSFT:99"
    assert data["exit_identity"]["entry_canonical_intelligence_hash"] == "b" * 64
    assert data["exit_trigger"]["trigger"] == "peak_lock_floor"
    assert data["canonical_intelligence_state"]["hash"] == "a" * 64
    assert (
        data["canonical_intelligence_state"]["momentum_state"]["session_label"] == "strong_uptrend"
    )
    assert data["realized_outcome"]["capture_ratio"] == 0.525
    assert data["realized_outcome"]["max_adverse_excursion_pct"] == -0.35
    assert data["foregone_outcome"]["avoided_drawdown_pct"] == 0.3
    assert data["post_exit_path"]["return_60m_pct"] == -0.35
    assert len(data["exit_snapshot_hash"]) == 64


def test_canonical_exit_contract_requires_sections_and_size_limit():
    snapshot = _snapshot()
    result = validate_canonical_exit_snapshot_contract(snapshot)

    assert result["ok"] is True
    assert result["missing_sections"] == []
    assert result["json_size_bytes"] <= CANONICAL_EXIT_MAX_JSON_BYTES
    for section in CANONICAL_EXIT_REQUIRED_SECTIONS:
        assert section in snapshot.to_dict()


def test_canonical_exit_hash_is_stable_for_dict_insertion_order():
    first = _snapshot(
        realized_outcome={
            "realized_pnl": 12.5,
            "realized_return_pct": 0.42,
            "mfe_pct": 0.8,
            "capture_ratio": 0.525,
        },
        foregone_outcome={
            "avoided_drawdown_pct": 0.3,
            "missed_upside_pct": 0.1,
        },
    )
    second = _snapshot(
        realized_outcome={
            "capture_ratio": 0.525,
            "mfe_pct": 0.8,
            "realized_return_pct": 0.42,
            "realized_pnl": 12.5,
        },
        foregone_outcome={
            "missed_upside_pct": 0.1,
            "avoided_drawdown_pct": 0.3,
        },
    )

    assert first.exit_snapshot_hash == second.exit_snapshot_hash


def test_canonical_exit_hash_normalizes_float_formatting():
    first = _snapshot(realized_outcome={"capture_ratio": 0.1 + 0.2})
    second = _snapshot(realized_outcome={"capture_ratio": 0.3})

    assert first.exit_snapshot_hash == second.exit_snapshot_hash


def test_canonical_exit_hash_normalizes_scalar_list_order_in_entry_state():
    first = _snapshot(
        canonical_intelligence=_canonical_intelligence(
            regime_state={"overlap_symbols": ["NVDA", "AMD"]}
        )
    )
    second = _snapshot(
        canonical_intelligence=_canonical_intelligence(
            regime_state={"overlap_symbols": ["AMD", "NVDA"]}
        )
    )

    assert first.exit_snapshot_hash == second.exit_snapshot_hash


def test_canonical_exit_persistence_writes_queryable_row():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "exit.db"
        snapshot = _snapshot()
        service = ExitSnapshotService(ExitSnapshotRepository(db_path))

        row_id = service.persist(snapshot)

        rows = _rows(db_path)
        assert row_id == 1
        assert len(rows) == 1
        row = rows[0]
        assert row["symbol"] == "MSFT"
        assert row["decision_snapshot_id"] == 303
        assert row["entry_trade_id"] == 99
        assert row["position_id"] == "MSFT:99"
        assert row["exit_trigger"] == "peak_lock_floor"
        assert row["exit_source"] == "position_manager"
        assert row["realized_pnl"] == 12.5
        assert row["capture_ratio"] == 0.525
        assert row["max_adverse_excursion_pct"] == -0.35
        assert row["reentry_window_summary"] == "no_clean_reentry_60m"
        assert row["realized_exit_label_version"] == REALIZED_EXIT_LABEL_VERSION
        assert row["exit_policy_version"] == EXIT_POLICY_VERSION
        assert row["position_manager_version"] == POSITION_MANAGER_VERSION
        assert row["canonical_exit_version"] == CANONICAL_EXIT_VERSION
        assert row["canonical_exit_hash"] == snapshot.exit_snapshot_hash
        assert row["canonical_intelligence_hash"] == "a" * 64
        assert row["entry_canonical_intelligence_version"] == "canonical_intelligence_v1"
        assert row["entry_canonical_intelligence_hash"] == "b" * 64
        assert json.loads(row["exit_regime_state_json"])["macro_regime"] == "risk_on"
        assert json.loads(row["exit_momentum_state_json"])["session_label"] == "strong_uptrend"
        assert json.loads(row["exit_trend_state_json"])["direction"] == "bullish"
        persisted = json.loads(row["canonical_exit_json"])
        assert persisted["exit_snapshot_hash"] == snapshot.exit_snapshot_hash


def test_canonical_exit_snapshot_stays_below_size_limit():
    assert canonical_exit_json_size_bytes(_snapshot()) < CANONICAL_EXIT_MAX_JSON_BYTES


def main():
    tests = [
        test_build_canonical_exit_snapshot_collects_exit_state_and_hashes,
        test_canonical_exit_contract_requires_sections_and_size_limit,
        test_canonical_exit_hash_is_stable_for_dict_insertion_order,
        test_canonical_exit_hash_normalizes_float_formatting,
        test_canonical_exit_hash_normalizes_scalar_list_order_in_entry_state,
        test_canonical_exit_persistence_writes_queryable_row,
        test_canonical_exit_snapshot_stays_below_size_limit,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} canonical exit snapshot tests passed.")


if __name__ == "__main__":
    main()
