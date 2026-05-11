import sqlite3
from pathlib import Path

import fill_stream


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


def trade_order_exists(order_id: str) -> bool:
    """Return True if trades already contains this order_id.

    Used to make synthetic bracket-exit insertion idempotent when Alpaca
    reconnects or replays a fill event.
    """
    if not order_id:
        return False

    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT id FROM trades WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
        con.close()
        return row is not None
    except Exception as e:
        logger.error(f"trade_order_exists failed for order {order_id}: {e}")
        return False

    assert fill_stream.trade_order_exists("existing-order-1") is True
    assert fill_stream.trade_order_exists("missing-order") is False
