import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories import context_repo, trades_repo
from repositories.trade_matcher_repo import TradeMatcherRepository


TEMP_DIRS = []


def make_trade_accounting_db() -> Path:
    tmpdir = tempfile.TemporaryDirectory()
    TEMP_DIRS.append(tmpdir)
    db_path = Path(tmpdir.name) / "trades.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                order_id TEXT,
                order_status TEXT,
                qty INTEGER,
                fill_price REAL,
                rejection_reason TEXT
            )
            """
        )
    return db_path


def insert_trade(
    db_path: Path,
    *,
    timestamp: str,
    symbol: str = "GE",
    action: str,
    status: str,
    qty: int,
    fill_price: float | None,
    order_id: str,
    rejection_reason: str | None = None,
) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO trades (
                timestamp, symbol, action, approved, order_id, order_status,
                qty, fill_price, rejection_reason
            ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                symbol,
                action,
                order_id,
                status,
                qty,
                fill_price,
                rejection_reason,
            ),
        )


def test_canceled_order_with_fill_counts_for_open_position_accounting():
    db_path = make_trade_accounting_db()
    insert_trade(
        db_path,
        timestamp="2026-06-01 09:25:00",
        action="buy",
        status="filled",
        qty=3,
        fill_price=323.78,
        order_id="buy-1",
    )
    insert_trade(
        db_path,
        timestamp="2026-06-01 09:38:00",
        action="sell",
        status="canceled",
        qty=1,
        fill_price=318.00,
        order_id="sell-canceled-partial",
    )
    insert_trade(
        db_path,
        timestamp="2026-06-01 09:42:00",
        action="sell",
        status="filled",
        qty=2,
        fill_price=318.71,
        order_id="sell-2",
    )

    assert trades_repo.has_open_position("GE", db_path=db_path) is False
    assert context_repo.startup_db_open_symbols(db_path=db_path) == []


def test_empty_canceled_order_does_not_count_as_fill_bearing_trade():
    db_path = make_trade_accounting_db()
    insert_trade(
        db_path,
        timestamp="2026-06-01 09:25:00",
        action="buy",
        status="filled",
        qty=3,
        fill_price=323.78,
        order_id="buy-1",
    )
    insert_trade(
        db_path,
        timestamp="2026-06-01 09:38:00",
        action="sell",
        status="canceled",
        qty=3,
        fill_price=None,
        order_id="sell-empty-canceled",
    )

    assert trades_repo.has_open_position("GE", db_path=db_path) is True


def test_trade_matcher_repository_loads_canceled_fill_bearing_rows():
    db_path = make_trade_accounting_db()
    insert_trade(
        db_path,
        timestamp="2026-06-01 09:25:00",
        action="buy",
        status="filled",
        qty=1,
        fill_price=323.78,
        order_id="buy-1",
    )
    insert_trade(
        db_path,
        timestamp="2026-06-01 09:38:00",
        action="sell",
        status="canceled",
        qty=1,
        fill_price=318.00,
        order_id="sell-canceled-partial",
        rejection_reason="position_manager_full_exit: test",
    )

    rows = TradeMatcherRepository(db_path).load_filled_trades()
    assert [row["order_id"] for row in rows] == ["buy-1", "sell-canceled-partial"]

    pm_sells = TradeMatcherRepository(db_path).load_position_manager_sells()
    assert [row["order_id"] for row in pm_sells] == ["sell-canceled-partial"]


if __name__ == "__main__":
    tests = [
        test_canceled_order_with_fill_counts_for_open_position_accounting,
        test_empty_canceled_order_does_not_count_as_fill_bearing_trade,
        test_trade_matcher_repository_loads_canceled_fill_bearing_rows,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} trade accounting tests passed.")
