import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fill_stream


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

    def test_get_connection():
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(fill_stream, "get_connection", test_get_connection)

    inserted_first = fill_stream.insert_synthetic_exit(
        order_id="child-sell-1",
        symbol="AAPL",
        side="sell",
        status="filled",
        filled_qty=10,
        fill_price=105.50,
        parent_order_id="parent-buy-1",
    )

    inserted_second = fill_stream.insert_synthetic_exit(
        order_id="child-sell-1",
        symbol="AAPL",
        side="sell",
        status="filled",
        filled_qty=10,
        fill_price=105.50,
        parent_order_id="parent-buy-1",
    )

    assert inserted_first is True
    assert inserted_second is True
    assert count_trades(db_path) == 1


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

    def test_get_connection():
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(fill_stream, "get_connection", test_get_connection)

    assert fill_stream.trade_order_exists(insert_order_id) is True
    assert fill_stream.trade_order_exists("missing-order") is False


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

    def test_get_connection():
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(fill_stream, "get_connection", test_get_connection)

    rows = fill_stream.update_db(order_id, "filled", 147.352, filled_qty=5)

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
        test_trade_order_exists_checks_order_id,
        test_update_db_refreshes_cumulative_filled_qty,
    ]
    for test in tests:
        run_with_temp_db(test)
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} fill stream tests passed.")
