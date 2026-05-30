import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_layer import ledger
from repositories.ledger_repo import LedgerRepository


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "trades.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                action TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE fill_events (
                id INTEGER PRIMARY KEY,
                order_id TEXT
            )
            """
        )
        con.execute("INSERT INTO trades (id, symbol, action) VALUES (1, 'AAPL', 'buy')")
        con.execute("INSERT INTO trades (id, symbol, action) VALUES (2, 'QQQ', 'sell')")
    return db_path


def test_ledger_repository_summarizes_tables(tmp_path):
    repo = LedgerRepository(db_path=_make_db(tmp_path))

    summary = repo.ledger_summary()

    assert summary["has_trades"] is True
    assert summary["has_matched_trades"] is False
    assert summary["has_fill_events"] is True
    assert summary["trades_count"] == 2
    assert summary["matched_trades_count"] == 0
    assert summary["fill_events_count"] == 0
    assert summary["trades_columns"] == ["id", "symbol", "action"]


def test_latest_trade_rows_clamps_limit_and_orders_desc(tmp_path):
    repo = LedgerRepository(db_path=_make_db(tmp_path))

    rows = repo.latest_trade_rows(limit=1000)

    assert [row["id"] for row in rows] == [2, 1]


def test_data_layer_ledger_wrapper_delegates_to_repository(tmp_path):
    db_path = _make_db(tmp_path)

    assert ledger.table_exists("trades", db_path=db_path) is True
    assert ledger.count_rows("trades", db_path=db_path) == 2
    assert ledger.latest_trade_rows(limit=1, db_path=db_path)[0]["symbol"] == "QQQ"


if __name__ == "__main__":
    import tempfile

    tests = [
        test_ledger_repository_summarizes_tables,
        test_latest_trade_rows_clamps_limit_and_orders_desc,
        test_data_layer_ledger_wrapper_delegates_to_repository,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ledger repository tests passed.")
