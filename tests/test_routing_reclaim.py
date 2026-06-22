"""Tests for the ROUTING reclaim sweeper (#9).

A crash between claim_candidates (commits ROUTING) and mark_routed leaves a row
stranded in ROUTING. The sweeper reconciles it against the broker's open orders
by the deterministic client_order_id (auto-bridge-{id}-{symbol}).
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from repositories import auto_buy_repo
from repositories.discovery_execution_bridge_repo import (
    ROUTING,
    DiscoveryExecutionBridgeRepository,
)
from services.discovery_execution_bridge_service import (
    DiscoveryBridgeConfig,
    DiscoveryExecutionBridgeService,
)


class _Broker:
    def __init__(self, open_orders=None):
        self.open_orders = open_orders or []

    def list_open_orders(self, symbol=None):
        return self.open_orders


def _insert_routing_row(db_path, *, symbol="AAPL", attempted_at):
    candidate = {"symbol": symbol, "decision": "strong_buy_candidate", "score": 20.0}
    auto_buy_repo.insert_candidate_and_snapshot(
        timestamp="2026-06-09T09:00:00-04:00",
        created_at="2026-06-09T09:00:01-04:00",
        candidate=candidate,
        live_buy_enabled=True,
        order={},
        candidate_json=json.dumps(candidate),
        order_json="{}",
        db_path=db_path,
    )
    with auto_buy_repo.get_connection(db_path) as con:
        row = con.execute(
            "SELECT id FROM auto_buy_decision_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        row_id = int(row["id"])
        con.execute(
            "UPDATE auto_buy_decision_snapshots "
            "SET execution_status = ?, execution_attempted_at = ? WHERE id = ?",
            (ROUTING, attempted_at, row_id),
        )
    return row_id


def _status(db_path, row_id):
    with auto_buy_repo.get_connection(db_path) as con:
        row = con.execute(
            "SELECT execution_status, execution_error FROM auto_buy_decision_snapshots WHERE id = ?",
            (row_id,),
        ).fetchone()
    return dict(row)


def _service(db_path, broker):
    return DiscoveryExecutionBridgeService(
        broker=broker,
        config=DiscoveryBridgeConfig(execution_mode="paper", routing_stale_seconds=300),
        db_path=db_path,
    )


def test_stale_routing_rows_only_returns_old_routing():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "trades.db"
        auto_buy_repo.init_tables(db)
        old_id = _insert_routing_row(db, symbol="AAPL", attempted_at="2020-01-01T00:00:00+00:00")
        _insert_routing_row(db, symbol="MSFT", attempted_at="2999-01-01T00:00:00+00:00")
        repo = DiscoveryExecutionBridgeRepository(db_path=db)
        stale = repo.stale_routing_rows(stale_cutoff="2026-01-01T00:00:00+00:00")
        ids = [int(r["id"]) for r in stale]
        assert ids == [old_id]  # the future-dated MSFT row is not stale


def test_reclaim_routes_when_open_order_matches():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "trades.db"
        auto_buy_repo.init_tables(db)
        row_id = _insert_routing_row(db, symbol="AAPL", attempted_at="2020-01-01T00:00:00+00:00")
        broker = _Broker(
            open_orders=[
                {
                    "id": "order-99",
                    "client_order_id": f"auto-bridge-{row_id}-AAPL",
                    "symbol": "AAPL",
                    "qty": "1",
                    "status": "new",
                }
            ]
        )
        results = _service(db, broker).reclaim_stranded_routing()
        assert len(results) == 1
        assert results[0].status == "ROUTED"
        assert _status(db, row_id)["execution_status"] == "ROUTED"


def test_reclaim_marks_failed_when_no_matching_open_order():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "trades.db"
        auto_buy_repo.init_tables(db)
        row_id = _insert_routing_row(db, symbol="AAPL", attempted_at="2020-01-01T00:00:00+00:00")
        broker = _Broker(open_orders=[])  # nothing matches -> unconfirmed
        results = _service(db, broker).reclaim_stranded_routing()
        assert len(results) == 1
        assert results[0].status == "FAILED"
        status = _status(db, row_id)
        assert status["execution_status"] == "FAILED"
        assert "needs_review" in (status["execution_error"] or "")


def test_reclaim_noop_in_cash_mode():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "trades.db"
        auto_buy_repo.init_tables(db)
        _insert_routing_row(db, symbol="AAPL", attempted_at="2020-01-01T00:00:00+00:00")
        service = DiscoveryExecutionBridgeService(
            broker=_Broker(),
            config=DiscoveryBridgeConfig(execution_mode="cash_full", routing_stale_seconds=300),
            db_path=db,
        )
        assert service.reclaim_stranded_routing() == []
