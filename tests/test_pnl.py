import sqlite3
from pathlib import Path

import pnl


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
            order_status TEXT,
            qty REAL,
            fill_price REAL,
            order_id TEXT
        )
        """
    )
    con.commit()
    con.close()

    return db_path


def insert_trade(
    db_path,
    timestamp,
    symbol,
    action,
    qty,
    fill_price,
    *,
    signal_price=None,
    approved=1,
    order_status="filled",
    order_id="test-order",
):
    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO trades (
            timestamp, symbol, action, qty, fill_price,
            signal_price, approved, order_status, order_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp,
            symbol,
            action,
            qty,
            fill_price,
            signal_price,
            approved,
            order_status,
            order_id,
        ),
    )
    con.commit()
    con.close()


def test_daily_realized_pnl_uses_confirmed_fills_only(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)
    monkeypatch.setattr(pnl, "DB_PATH", db_path)

    insert_trade(db_path, "2026-05-11 10:00:00", "AAPL", "buy", 10, 100.00)
    insert_trade(db_path, "2026-05-11 11:00:00", "AAPL", "sell", 10, 105.00)

    assert pnl.get_daily_realized_pnl("2026-05-11") == 50.00


def test_daily_realized_pnl_ignores_null_fill_price_even_with_signal_price(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)
    monkeypatch.setattr(pnl, "DB_PATH", db_path)

    insert_trade(db_path, "2026-05-11 10:00:00", "AAPL", "buy", 10, 100.00)
    insert_trade(
        db_path,
        "2026-05-11 11:00:00",
        "AAPL",
        "sell",
        10,
        None,
        signal_price=999.00,
    )

    assert pnl.get_daily_realized_pnl("2026-05-11") == 0.00


def test_daily_realized_pnl_ignores_unapproved_rows(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)
    monkeypatch.setattr(pnl, "DB_PATH", db_path)

    insert_trade(db_path, "2026-05-11 10:00:00", "AAPL", "buy", 10, 100.00)
    insert_trade(
        db_path,
        "2026-05-11 11:00:00",
        "AAPL",
        "sell",
        10,
        105.00,
        approved=0,
    )

    assert pnl.get_daily_realized_pnl("2026-05-11") == 0.00


def test_daily_realized_pnl_ignores_non_filled_statuses(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)
    monkeypatch.setattr(pnl, "DB_PATH", db_path)

    insert_trade(db_path, "2026-05-11 10:00:00", "AAPL", "buy", 10, 100.00)
    insert_trade(
        db_path,
        "2026-05-11 11:00:00",
        "AAPL",
        "sell",
        10,
        105.00,
        order_status="new",
    )

    assert pnl.get_daily_realized_pnl("2026-05-11") == 0.00


def test_daily_realized_pnl_fifo_multi_lot(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)
    monkeypatch.setattr(pnl, "DB_PATH", db_path)

    insert_trade(db_path, "2026-05-11 10:00:00", "AAPL", "buy", 5, 100.00)
    insert_trade(db_path, "2026-05-11 10:30:00", "AAPL", "buy", 5, 110.00)
    insert_trade(db_path, "2026-05-11 11:00:00", "AAPL", "sell", 8, 120.00)

    # FIFO:
    # 5 shares: 120 - 100 = 20 * 5 = 100
    # 3 shares: 120 - 110 = 10 * 3 = 30
    assert pnl.get_daily_realized_pnl("2026-05-11") == 130.00


def test_daily_realized_pnl_unmatched_sell_does_not_create_fake_pnl(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)
    monkeypatch.setattr(pnl, "DB_PATH", db_path)

    insert_trade(db_path, "2026-05-11 11:00:00", "AAPL", "sell", 10, 105.00)

    assert pnl.get_daily_realized_pnl("2026-05-11") == 0.00


def test_daily_realized_pnl_filters_by_date(tmp_path, monkeypatch):
    db_path = make_test_db(tmp_path)
    monkeypatch.setattr(pnl, "DB_PATH", db_path)

    insert_trade(db_path, "2026-05-10 10:00:00", "AAPL", "buy", 10, 100.00)
    insert_trade(db_path, "2026-05-10 11:00:00", "AAPL", "sell", 10, 105.00)

    insert_trade(db_path, "2026-05-11 10:00:00", "MSFT", "buy", 10, 200.00)
    insert_trade(db_path, "2026-05-11 11:00:00", "MSFT", "sell", 10, 210.00)

    assert pnl.get_daily_realized_pnl("2026-05-11") == 100.00
