#!/usr/bin/env python3
"""Tests for paper-only discovery-to-execution bridge."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src" / "trading_bot"))

import services.discovery_execution_bridge_service as bridge_module
from services.discovery_execution_bridge_service import (
    FAILED,
    PENDING,
    REASON_CODE_ALLOCATION_ROUNDS_TO_ZERO,
    REASON_CODE_BROKER_TRANSIENT_FAILURE,
    REASON_CODE_CONVICTION_ENTRY_BLOCK,
    REASON_CODE_COOLDOWN_ACTIVE,
    REASON_CODE_MISSING_CANONICAL_TRACE,
    REASON_CODE_OPEN_ORDER_EXISTS,
    REASON_CODE_OPEN_POSITION_EXISTS,
    ROUTED,
    DiscoveryBridgeConfig,
    DiscoveryExecutionBridgeService,
)

from config.conviction import load_conviction_config
from repositories import auto_buy_repo

_DEFAULT_ORDER = object()


class FakeBroker:
    def __init__(
        self,
        order=_DEFAULT_ORDER,
        position=None,
        open_orders=None,
        failure_reason=None,
        positions=None,
    ):
        self.order = {"id": "order-1", "status": "submitted"} if order is _DEFAULT_ORDER else order
        self.position = position
        self.open_orders = open_orders or []
        self.failure_reason = failure_reason
        self.positions = positions or []
        self.calls = []

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return self.order

    def last_order_failure_reason(self):
        return self.failure_reason

    def get_position(self, symbol):
        return self.position

    def list_open_orders(self, symbol=None):
        return self.open_orders

    def list_positions(self):
        return self.positions


class FakeLogger:
    def __init__(self):
        self.info_calls = []

    def info(self, message, *args):
        self.info_calls.append((message, args))


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
    _ensure_trades_table(db_path)
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


def _ensure_trades_table(db_path: Path) -> None:
    with auto_buy_repo.get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT,
                action TEXT,
                signal_price REAL,
                approved INTEGER,
                rejection_reason TEXT,
                confidence TEXT,
                position_size_pct REAL,
                stop_loss_pct REAL,
                take_profit_pct REAL,
                order_id TEXT,
                order_status TEXT,
                qty INTEGER,
                fill_price REAL,
                market_bias TEXT,
                risk_level TEXT,
                entry_quality TEXT,
                session_trend_label TEXT,
                session_trend_score REAL,
                session_return_pct REAL,
                session_momentum_5m_pct REAL,
                session_momentum_15m_pct REAL,
                session_momentum_30m_pct REAL,
                session_distance_from_vwap_pct REAL,
                setup_label TEXT,
                setup_policy_action TEXT,
                setup_policy_reason TEXT,
                prediction_score REAL,
                prediction_decision TEXT,
                prediction_reason TEXT,
                ml_prediction_score REAL,
                ml_prediction_bucket TEXT,
                buy_opportunity_score REAL,
                buy_opportunity_recommendation TEXT,
                buy_opportunity_reason TEXT,
                session_momentum_severity TEXT,
                effective_size_cap_pct REAL,
                dominant_limiter TEXT
            )
            """
        )


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


def _service(db_path: Path, broker: FakeBroker, min_score=13.0, logger=None):
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
        logger=logger,
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
        assert results[0].reason_code == REASON_CODE_MISSING_CANONICAL_TRACE
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
        with auto_buy_repo.get_connection(db_path) as con:
            trade = con.execute(
                """
                SELECT symbol, action, order_id, order_status, qty,
                       position_size_pct, stop_loss_pct, take_profit_pct,
                       signal_price
                FROM trades
                WHERE order_id = ?
                """,
                ("order-123",),
            ).fetchone()
        assert trade["symbol"] == "AAPL"
        assert trade["action"] == "buy"
        assert trade["order_status"] == "filled"
        assert trade["qty"] is None
        assert trade["position_size_pct"] == 0.25
        assert trade["stop_loss_pct"] == 1.0
        assert trade["take_profit_pct"] == 2.0


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
        assert len(second) == 1
        assert second[0].status == FAILED
        assert second[0].reason_code == REASON_CODE_COOLDOWN_ACTIVE
        assert "symbol cooldown active" in second[0].reason
        assert len(broker.calls) == 1
        assert row["execution_status"] == FAILED


def test_existing_open_position_blocks_bridge_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        row_id = _insert_snapshot(db_path, _candidate(score=20.0, trace=_approved_trace()))
        broker = FakeBroker(position={"qty": "1"})
        logger = FakeLogger()

        results = _service(db_path, broker, logger=logger).route_eligible_candidates()

        row = _status(db_path, row_id)
        assert len(results) == 1
        assert results[0].status == FAILED
        assert results[0].reason_code == REASON_CODE_OPEN_POSITION_EXISTS
        assert "existing open position" in results[0].reason
        assert broker.calls == []
        assert logger.info_calls
        assert logger.info_calls[0][1][0] == row_id
        assert logger.info_calls[0][1][2] == REASON_CODE_OPEN_POSITION_EXISTS
        assert row["execution_status"] == FAILED


def test_existing_open_order_blocks_bridge_route_with_reason_code():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        row_id = _insert_snapshot(db_path, _candidate(score=20.0, trace=_approved_trace()))
        broker = FakeBroker(open_orders=[{"id": "open-order-1"}])
        logger = FakeLogger()

        results = _service(db_path, broker, logger=logger).route_eligible_candidates()

        row = _status(db_path, row_id)
        assert len(results) == 1
        assert results[0].status == FAILED
        assert results[0].reason_code == REASON_CODE_OPEN_ORDER_EXISTS
        assert "existing open order" in results[0].reason
        assert broker.calls == []
        assert logger.info_calls[0][1][0] == row_id
        assert logger.info_calls[0][1][2] == REASON_CODE_OPEN_ORDER_EXISTS
        assert row["execution_status"] == FAILED


def test_symbol_cooldown_drop_logs_candidate_tracking_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        logger = FakeLogger()
        broker = FakeBroker(order={"id": "order-1", "status": "filled"})
        service = _service(db_path, broker, logger=logger)
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
        service.route_eligible_candidates()
        second_id = _insert_snapshot(
            db_path,
            _candidate(symbol="BURL", score=21.0, trace=_approved_trace()),
            timestamp="2026-06-09T14:02:00-04:00",
        )

        service.route_eligible_candidates()

        assert logger.info_calls
        assert logger.info_calls[-1][1][0] == second_id
        assert logger.info_calls[-1][1][1] == "BURL"
        assert logger.info_calls[-1][1][2] == REASON_CODE_COOLDOWN_ACTIVE
        assert "symbol cooldown active" in logger.info_calls[-1][1][3]


def test_full_share_allocation_rounding_blocks_before_broker_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        candidate = _candidate(symbol="ASML", score=22.0, trace=_approved_trace())
        candidate["current_price"] = 980.0
        candidate["account_equity"] = 50_000.0
        candidate["effective_size_cap_pct"] = 0.25
        row_id = _insert_snapshot(db_path, candidate)
        broker = FakeBroker(order={"id": "order-should-not-route", "status": "filled"})
        logger = FakeLogger()

        results = _service(db_path, broker, logger=logger).route_eligible_candidates()

        row = _status(db_path, row_id)
        assert len(results) == 1
        assert results[0].status == FAILED
        assert results[0].reason_code == REASON_CODE_ALLOCATION_ROUNDS_TO_ZERO
        assert "allocation rounds below minimum trade quantity" in results[0].reason
        assert broker.calls == []
        assert row["execution_status"] == FAILED
        assert logger.info_calls[-1][1][2] == REASON_CODE_ALLOCATION_ROUNDS_TO_ZERO


def test_conviction_entry_block_fails_candidate_before_broker_route():
    old_cfg = bridge_module._CONVICTION_CFG
    bridge_module._CONVICTION_CFG = load_conviction_config(
        enabled=True,
        min_score=30.0,
        require_probability=True,
    )
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "trades.db"
            auto_buy_repo.init_tables(db_path)
            candidate = _candidate(symbol="MSFT", score=45.0, trace=_approved_trace())
            candidate["market_context_ok"] = True
            row_id = _insert_snapshot(db_path, candidate)
            broker = FakeBroker(order={"id": "order-should-not-route", "status": "filled"})
            logger = FakeLogger()

            results = _service(db_path, broker, logger=logger).route_eligible_candidates()

            row = _status(db_path, row_id)
            assert len(results) == 1
            assert results[0].status == FAILED
            assert results[0].reason_code == REASON_CODE_CONVICTION_ENTRY_BLOCK
            assert "probability_unavailable" in results[0].reason
            assert broker.calls == []
            assert row["execution_status"] == FAILED
            assert logger.info_calls[-1][1][2] == REASON_CODE_CONVICTION_ENTRY_BLOCK
    finally:
        bridge_module._CONVICTION_CFG = old_cfg


def test_conviction_entry_replaces_request_with_conviction_size():
    old_cfg = bridge_module._CONVICTION_CFG
    bridge_module._CONVICTION_CFG = load_conviction_config(
        enabled=True,
        min_score=30.0,
        position_size_pct=90.0,
    )
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "trades.db"
            auto_buy_repo.init_tables(db_path)
            candidate = _candidate(symbol="MSFT", score=45.0, trace=_approved_trace())
            candidate["layered_ml_ensemble_probability_pct"] = 70.0
            candidate["market_context_ok"] = True
            row_id = _insert_snapshot(db_path, candidate)
            broker = FakeBroker(order={"id": "order-123", "status": "filled"})

            results = _service(db_path, broker).route_eligible_candidates()

            row = _status(db_path, row_id)
            assert len(results) == 1
            assert results[0].status == ROUTED
            assert broker.calls[0]["position_size_pct"] == 90.0
            assert row["execution_status"] == ROUTED
            with auto_buy_repo.get_connection(db_path) as con:
                trade = con.execute(
                    "SELECT position_size_pct FROM trades WHERE order_id = ?",
                    ("order-123",),
                ).fetchone()
            assert trade["position_size_pct"] == 90.0
    finally:
        bridge_module._CONVICTION_CFG = old_cfg


def test_conviction_entry_accepts_daily_profit_probability_fallback():
    old_cfg = bridge_module._CONVICTION_CFG
    bridge_module._CONVICTION_CFG = load_conviction_config(
        enabled=True,
        min_score=23.0,
        min_probability_pct=62.0,
    )
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "trades.db"
            auto_buy_repo.init_tables(db_path)
            candidate = _candidate(symbol="MSFT", score=24.0, trace=_approved_trace())
            candidate["probability_pct"] = 64.0
            candidate["probability_source"] = "daily_symbol_predictions:probability_of_profit"
            candidate["market_context_ok"] = True
            row_id = _insert_snapshot(db_path, candidate)
            broker = FakeBroker(order={"id": "order-profit-prob", "status": "filled"})

            results = _service(db_path, broker).route_eligible_candidates()

            row = _status(db_path, row_id)
            assert len(results) == 1
            assert results[0].status == ROUTED
            assert broker.calls
            assert row["execution_status"] == ROUTED
    finally:
        bridge_module._CONVICTION_CFG = old_cfg


def test_conviction_entry_requires_stricter_system_probability_fallback():
    old_cfg = bridge_module._CONVICTION_CFG
    bridge_module._CONVICTION_CFG = load_conviction_config(
        enabled=True,
        min_score=23.0,
        min_probability_pct=62.0,
        min_system_probability_pct=80.0,
    )
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "trades.db"
            auto_buy_repo.init_tables(db_path)
            candidate = _candidate(symbol="MSFT", score=24.0, trace=_approved_trace())
            candidate["probability_pct"] = 70.0
            candidate["probability_source"] = "daily_symbol_predictions:probability_of_order"
            candidate["market_context_ok"] = True
            row_id = _insert_snapshot(db_path, candidate)
            broker = FakeBroker(order={"id": "order-should-not-route", "status": "filled"})

            results = _service(db_path, broker).route_eligible_candidates()

            row = _status(db_path, row_id)
            assert len(results) == 1
            assert results[0].status == FAILED
            assert results[0].reason_code == REASON_CODE_CONVICTION_ENTRY_BLOCK
            assert "probability_below_bar" in results[0].reason
            assert broker.calls == []
            assert row["execution_status"] == FAILED
    finally:
        bridge_module._CONVICTION_CFG = old_cfg


def test_transient_broker_submit_failure_returns_candidate_to_pending():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        auto_buy_repo.init_tables(db_path)
        row_id = _insert_snapshot(db_path, _candidate(score=20.0, trace=_approved_trace()))
        broker = FakeBroker(order=None, failure_reason="broker_submit_failed:too many requests.")
        logger = FakeLogger()

        results = _service(db_path, broker, logger=logger).route_eligible_candidates()

        row = _status(db_path, row_id)
        assert len(results) == 1
        assert results[0].status == PENDING
        assert results[0].reason_code == REASON_CODE_BROKER_TRANSIENT_FAILURE
        assert "too many requests" in results[0].reason
        assert row["execution_status"] == PENDING
        assert row["order_submitted"] == 0
        assert "too many requests" in row["execution_error"]
        assert logger.info_calls[-1][1][2] == REASON_CODE_BROKER_TRANSIENT_FAILURE


def main() -> None:
    tests = [
        test_low_score_candidate_remains_pending_and_is_not_routed,
        test_strong_candidate_without_canonical_trace_is_failed_without_routing,
        test_successfully_routed_candidate_cannot_be_resubmitted,
        test_older_strong_candidate_is_not_routed_when_latest_symbol_snapshot_is_skip,
        test_recent_routed_symbol_cooldown_blocks_reentry,
        test_existing_open_position_blocks_bridge_route,
        test_existing_open_order_blocks_bridge_route_with_reason_code,
        test_symbol_cooldown_drop_logs_candidate_tracking_id,
        test_full_share_allocation_rounding_blocks_before_broker_route,
        test_conviction_entry_block_fails_candidate_before_broker_route,
        test_conviction_entry_replaces_request_with_conviction_size,
        test_transient_broker_submit_failure_returns_candidate_to_pending,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} discovery execution bridge tests passed.")


if __name__ == "__main__":
    main()
