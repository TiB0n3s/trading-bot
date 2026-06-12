import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.fill_stream_service import (
    DEFAULT_HEARTBEAT_SECONDS,
    FillEventHandler,
    FillStreamService,
    _fill_stream_heartbeat_seconds,
)

from repositories import fill_repo


class SimpleMonkeyPatch:
    def __init__(self):
        self._changes = []

    def setattr(self, obj, name, value):
        self._changes.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, original in reversed(self._changes):
            setattr(obj, name, original)


def make_test_db(tmp_path: Path):
    db_path = tmp_path / "trades.db"

    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE trades (
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
            fill_price REAL
        )
        """
    )
    con.commit()
    con.close()

    return db_path


def count_trades(db_path: Path):
    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    con.close()
    return count


def test_insert_synthetic_exit_is_idempotent_by_order_id(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)

    inserted_first = fill_repo.insert_synthetic_exit(
        order_id="child-sell-1",
        symbol="AAPL",
        side="sell",
        status="filled",
        filled_qty=10,
        fill_price=105.50,
        parent_order_id="parent-buy-1",
        db_path=db_path,
    )

    inserted_second = fill_repo.insert_synthetic_exit(
        order_id="child-sell-1",
        symbol="AAPL",
        side="sell",
        status="filled",
        filled_qty=10,
        fill_price=105.50,
        parent_order_id="parent-buy-1",
        db_path=db_path,
    )

    assert inserted_first is True
    assert inserted_second is False
    assert count_trades(db_path) == 1


def test_insert_synthetic_buy_fill_is_idempotent_by_order_id(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)

    inserted_first = fill_repo.insert_synthetic_fill(
        order_id="buy-fill-1",
        symbol="ASML",
        side="buy",
        status="filled",
        filled_qty=1,
        fill_price=980.25,
        db_path=db_path,
    )

    inserted_second = fill_repo.insert_synthetic_fill(
        order_id="buy-fill-1",
        symbol="ASML",
        side="buy",
        status="filled",
        filled_qty=1,
        fill_price=980.25,
        db_path=db_path,
    )

    con = sqlite3.connect(db_path)
    row = con.execute(
        "SELECT symbol, action, qty, fill_price, rejection_reason FROM trades WHERE order_id = ?",
        ("buy-fill-1",),
    ).fetchone()
    con.close()

    assert inserted_first is True
    assert inserted_second is False
    assert count_trades(db_path) == 1
    assert row[0] == "ASML"
    assert row[1] == "buy"
    assert row[2] == 1
    assert row[3] == 980.25
    assert row[4].startswith("synthetic_unmatched_buy_fill")


def test_trade_order_exists_checks_order_id(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)
    insert_order_id = "existing-order-1"

    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO trades (
            timestamp, symbol, action, signal_price, approved,
            order_id, order_status, qty, fill_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "2026-05-11 10:00:00",
            "AAPL",
            "buy",
            100.0,
            1,
            insert_order_id,
            "filled",
            1,
            100.0,
        ),
    )
    con.commit()
    con.close()

    assert fill_repo.trade_order_exists(insert_order_id, db_path=db_path) is True
    assert fill_repo.trade_order_exists("missing-order", db_path=db_path) is False


def test_update_db_refreshes_cumulative_filled_qty(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)
    order_id = "child-sell-1"

    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO trades (
            timestamp, symbol, action, signal_price, approved,
            order_id, order_status, qty, fill_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "2026-05-27 11:13:44",
            "RKLB",
            "sell",
            147.34,
            1,
            order_id,
            "partially_filled",
            1,
            147.34,
        ),
    )
    con.commit()
    con.close()

    rows = fill_repo.update_trade_fill(order_id, "filled", 147.352, filled_qty=5, db_path=db_path)

    con = sqlite3.connect(db_path)
    row = con.execute(
        "SELECT order_status, qty, fill_price FROM trades WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    con.close()

    assert rows == 1
    assert row[0] == "filled"
    assert row[1] == 5
    assert row[2] == 147.352


class FakeFillRepository:
    def __init__(self):
        self.events = []
        self.updated = []
        self.synthetic = []

    def record_fill_event(self, event, order):
        self.events.append((event, order))

    def update_trade_fill(self, order_id, status, fill_price, filled_qty):
        self.updated.append((order_id, status, fill_price, filled_qty))
        return 0

    def insert_synthetic_fill(self, **kwargs):
        self.synthetic.append(kwargs)
        return True

    def insert_synthetic_exit(self, **kwargs):
        raise AssertionError("buy fill should use insert_synthetic_fill")


class FakeFeedbackService:
    def __init__(self):
        self.calls = []

    def capture_performance_snapshot(
        self,
        target_date,
        *,
        phase,
        trigger_symbol=None,
        include_historical=True,
    ):
        self.calls.append(
            {
                "target_date": target_date,
                "phase": phase,
                "trigger_symbol": trigger_symbol,
                "include_historical": include_historical,
            }
        )
        return {
            "status": "neutral",
            "same_day_closed_trades": 0,
            "same_day_avg_pnl_pct": None,
            "evidence_keys": 0,
        }


class FakeTradingStream:
    instances = []

    def __init__(self, api_key, secret_key, paper=True, raw_data=False, url_override=None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.raw_data = raw_data
        self.url_override = url_override
        self.handler = None
        FakeTradingStream.instances.append(self)

    def subscribe_trade_updates(self, handler):
        self.handler = handler

    def run(self):
        return None


def test_unmatched_buy_fill_inserts_synthetic_ledger_row(tmp_path, monkeypatch):
    repo = FakeFillRepository()
    feedback = FakeFeedbackService()
    handler = FillEventHandler(
        repository=repo,
        feedback_service=feedback,
        market_hours_fn=lambda: True,
        logger=SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None
        ),
    )
    data = SimpleNamespace(
        event="fill",
        order={
            "id": "buy-order-1",
            "symbol": "ASML",
            "side": "buy",
            "status": "filled",
            "filled_qty": "1",
            "filled_avg_price": "980.25",
            "parent_order_id": None,
        },
    )

    asyncio.run(handler.trade_update_handler(data))

    assert repo.updated == [("buy-order-1", "filled", 980.25, "1")]
    assert repo.synthetic == [
        {
            "order_id": "buy-order-1",
            "symbol": "ASML",
            "side": "buy",
            "status": "filled",
            "filled_qty": "1",
            "fill_price": 980.25,
            "parent_order_id": None,
        }
    ]
    assert feedback.calls
    assert feedback.calls[0]["phase"] == "post_fill"
    assert feedback.calls[0]["trigger_symbol"] == "ASML"


def test_fill_stream_heartbeat_env_parser_falls_back_on_invalid_value(tmp_path, monkeypatch):
    original = os.environ.get("FILL_STREAM_HEARTBEAT_SECONDS")
    try:
        os.environ["FILL_STREAM_HEARTBEAT_SECONDS"] = "not-an-int"
        assert _fill_stream_heartbeat_seconds() == DEFAULT_HEARTBEAT_SECONDS

        os.environ["FILL_STREAM_HEARTBEAT_SECONDS"] = "60"
        assert _fill_stream_heartbeat_seconds() == 60
    finally:
        if original is None:
            os.environ.pop("FILL_STREAM_HEARTBEAT_SECONDS", None)
        else:
            os.environ["FILL_STREAM_HEARTBEAT_SECONDS"] = original


def test_fill_stream_uses_alpaca_py_trading_stream_constructor(tmp_path, monkeypatch):
    FakeTradingStream.instances = []
    handler = FillEventHandler(
        repository=FakeFillRepository(),
        feedback_service=FakeFeedbackService(),
        logger=SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None
        ),
    )
    service = FillStreamService(
        handler=handler,
        logger=SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None
        ),
        stream_cls=FakeTradingStream,
        api_key="key",
        secret_key="secret",
        base_url="https://paper-api.alpaca.markets",
    )

    service.run_stream()

    assert len(FakeTradingStream.instances) == 1
    instance = FakeTradingStream.instances[0]
    assert instance.paper is True
    assert instance.url_override is None
    assert instance.handler == handler.trade_update_handler


def run_with_temp_db(test_func):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch = SimpleMonkeyPatch()
        try:
            test_func(Path(tmp), monkeypatch)
        finally:
            monkeypatch.undo()


if __name__ == "__main__":
    tests = [
        test_insert_synthetic_exit_is_idempotent_by_order_id,
        test_insert_synthetic_buy_fill_is_idempotent_by_order_id,
        test_trade_order_exists_checks_order_id,
        test_update_db_refreshes_cumulative_filled_qty,
        test_unmatched_buy_fill_inserts_synthetic_ledger_row,
        test_fill_stream_heartbeat_env_parser_falls_back_on_invalid_value,
        test_fill_stream_uses_alpaca_py_trading_stream_constructor,
    ]
    for test in tests:
        run_with_temp_db(test)
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} fill stream tests passed.")
