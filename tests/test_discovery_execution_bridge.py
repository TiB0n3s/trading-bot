#!/usr/bin/env python3
"""Tests for paper-only discovery-to-execution bridge."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from repositories import auto_buy_repo
from services.discovery_execution_bridge_service import (
    FAILED,
    PENDING,
    ROUTED,
    DiscoveryBridgeConfig,
    DiscoveryExecutionBridgeService,
)


class FakeBroker:
    def __init__(self, order=None, position=None, open_orders=None):
        self.order = order or {"id": "order-1", "status": "submitted"}
        self.position = position
        self.open_orders = open_orders or []
        self.calls = []

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return self.order

    def last_order_failure_reason(self):
        return None

    def get_position(self, symbol):
        return self.position

    def list_open_orders(self, symbol=None):
        return self.open_orders


def _approved_trace():
    return {
        "trace_version": "decision_trace_v1",
        "final_decision": "approved",
        "gate_results": [
            {
                "gate_id": "execution_quality",
                "decision": "pass",
                "enforced": True,
            }
        ],
    }


def _candidate(symbol="AAPL", score=20.0, trace=None):
    candidate = {
        "symbol": symbol,
        "decision": "strong_buy_candidate",
        "score": score,
        "risk_level": "medium",
        "effective_size_cap_pct": 0.25,
    }
    if trace is not None:
        candidate["canonical_decision_trace"] = trace
    return candidate


def _insert_snapshot(
    db_path: Path,
    candidate: dict,
    *,
    live_buy_enabled=True,
    timestamp="2026-06-09T09:00:00-04:00",
) -> int:
    auto_buy_repo.insert_candidate_and_snapshot(
        timestamp=timestamp,
        created_at="2026-06-09T09:00:01-04:00",
        candidate=candidate,
        live_buy_enabled=live_buy_enabled,
        order={},
        candidate_json=json.dumps(candidate),
        order_json="{}",
        db_path=db_path,
    )
    with auto_buy_repo.get_connection(db_path) as con:
        row = con.execute(
            "SELECT id FROM auto_buy_decision_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return int(row["id"])


def _status(db_path: Path, row_id: int):
    with auto_buy_repo.get_connection(db_path) as con:
        return con.execute(
            """
            SELECT execution_status, routed_order_id, order_submitted, execution_error
            FROM auto_buy_decision_snapshots
            WHERE id = ?
            """,
            (row_id,),
        ).fetchone()


def _service(db_path: Path, broker: FakeBroker, min_score=13.0):
    return DiscoveryExecutionBridgeService(
        db_path=db_path,
        broker=broker,
        config=DiscoveryBridgeConfig(
            min_score=min_score,
            max_candidates_per_run=3,
            default_position_size_pct=0.5,
            stop_loss_pct=1.0,
            take_profit_pct=2.0,
            execution_mode="paper",
            target_date="2026-06-09",
            max_candidate_age_seconds=999999,
            symbol_cooldown_minutes=45,
        ),
    )


def test_low_score_candidate_remains_pending_and_is_not_routed():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        row_id = _insert_snapshot(db_path, _candidate(score=8.0, trace=_approved_trace()))
        broker = FakeBroker()

        results = _service(db_path, broker).route_eligible_candidates()

        row = _status(db_path, row_id)
        assert results == []
        assert broker.calls == []
        assert row["execution_status"] == PENDING
        assert row["order_submitted"] == 0


def test_strong_candidate_without_canonical_trace_is_failed_without_routing():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        row_id = _insert_snapshot(db_path, _candidate(score=20.0, trace=None))
        broker = FakeBroker()

        results = _service(db_path, broker).route_eligible_candidates()

        row = _status(db_path, row_id)
        assert len(results) == 1
        assert results[0].status == FAILED
        assert broker.calls == []
        assert row["execution_status"] == FAILED
        assert "missing canonical decision trace" in row["execution_error"]


def test_successfully_routed_candidate_cannot_be_resubmitted():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        row_id = _insert_snapshot(db_path, _candidate(score=20.0, trace=_approved_trace()))
        broker = FakeBroker(order={"id": "order-123", "status": "filled"})
        service = _service(db_path, broker)

        first = service.route_eligible_candidates()
        second = service.route_eligible_candidates()

        row = _status(db_path, row_id)
        assert len(first) == 1
        assert first[0].status == ROUTED
        assert first[0].routed_order_id == "order-123"
        assert second == []
        assert len(broker.calls) == 1
        assert broker.calls[0]["symbol"] == "AAPL"
        assert broker.calls[0]["position_size_pct"] == 0.25
        assert row["execution_status"] == ROUTED
        assert row["routed_order_id"] == "order-123"
        assert row["order_submitted"] == 1


def test_older_strong_candidate_is_not_routed_when_latest_symbol_snapshot_is_skip():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        old_id = _insert_snapshot(
            db_path,
            _candidate(symbol="RTX", score=24.0, trace=_approved_trace()),
            timestamp="2026-06-09T14:00:00-04:00",
        )
        _insert_snapshot(
            db_path,
            {
                "symbol": "RTX",
                "decision": "skip",
                "score": -5.0,
                "canonical_decision_trace": {"final_decision": "rejected"},
            },
            timestamp="2026-06-09T14:01:00-04:00",
        )
        broker = FakeBroker()

        results = _service(db_path, broker).route_eligible_candidates()

        row = _status(db_path, old_id)
        assert results == []
        assert broker.calls == []
        assert row["execution_status"] == PENDING


def test_recent_routed_symbol_cooldown_blocks_reentry():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        broker = FakeBroker(order={"id": "order-1", "status": "filled"})
        service = _service(db_path, broker)
        service.config = DiscoveryBridgeConfig(
            min_score=13.0,
            max_candidates_per_run=3,
            default_position_size_pct=0.5,
            stop_loss_pct=1.0,
            take_profit_pct=2.0,
            execution_mode="paper",
            target_date="2026-06-09",
            max_candidate_age_seconds=999999,
            symbol_cooldown_minutes=10000,
        )
        _insert_snapshot(
            db_path,
            _candidate(symbol="BURL", score=20.0, trace=_approved_trace()),
            timestamp="2026-06-09T14:00:00-04:00",
        )
        first = service.route_eligible_candidates()
        second_id = _insert_snapshot(
            db_path,
            _candidate(symbol="BURL", score=21.0, trace=_approved_trace()),
            timestamp="2026-06-09T14:02:00-04:00",
        )

        second = service.route_eligible_candidates()

        row = _status(db_path, second_id)
        assert len(first) == 1
        assert second == []
        assert len(broker.calls) == 1
        assert row["execution_status"] == PENDING


def test_existing_open_position_blocks_bridge_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        row_id = _insert_snapshot(db_path, _candidate(score=20.0, trace=_approved_trace()))
        broker = FakeBroker(position={"qty": "1"})

        results = _service(db_path, broker).route_eligible_candidates()

        row = _status(db_path, row_id)
        assert len(results) == 1
        assert results[0].status == FAILED
        assert "existing open position" in results[0].reason
        assert broker.calls == []
        assert row["execution_status"] == FAILED


def main() -> None:
    tests = [
        test_low_score_candidate_remains_pending_and_is_not_routed,
        test_strong_candidate_without_canonical_trace_is_failed_without_routing,
        test_successfully_routed_candidate_cannot_be_resubmitted,
        test_older_strong_candidate_is_not_routed_when_latest_symbol_snapshot_is_skip,
        test_recent_routed_symbol_cooldown_blocks_reentry,
        test_existing_open_position_blocks_bridge_route,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} discovery execution bridge tests passed.")


if __name__ == "__main__":
    main()
