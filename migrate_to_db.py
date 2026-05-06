import json
import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).parent / "trades.db"
LOG_PATH = Path(__file__).parent / "signals.log"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    symbol          TEXT,
    action          TEXT,
    signal_price    REAL,
    approved        INTEGER,
    rejection_reason TEXT,
    confidence      TEXT,
    position_size_pct REAL,
    stop_loss_pct   REAL,
    take_profit_pct REAL,
    order_id        TEXT,
    order_status    TEXT,
    qty             INTEGER,
    fill_price      REAL
)
"""

INSERT = """
INSERT INTO trades (
    timestamp, symbol, action, signal_price, approved, rejection_reason,
    confidence, position_size_pct, stop_loss_pct, take_profit_pct,
    order_id, order_status, qty, fill_price
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

LINE_RE = re.compile(
    r"^(?P<timestamp>.+?) \| SIGNAL: (?P<signal>\{.*?\}) \| DECISION: (?P<decision>\{.*?\}) \| ORDER: (?P<order>\{.*?\}|null)$"
)

def parse_line(line):
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    signal   = json.loads(m.group("signal"))
    decision = json.loads(m.group("decision"))
    order_raw = m.group("order")
    order = json.loads(order_raw) if order_raw != "null" else {}

    approved = decision.get("approved", False)
    return (
        m.group("timestamp"),
        signal.get("symbol"),
        signal.get("action"),
        signal.get("price"),
        1 if approved else 0,
        None if approved else decision.get("reason"),
        decision.get("confidence"),
        decision.get("position_size_pct"),
        decision.get("stop_loss_pct"),
        decision.get("take_profit_pct"),
        order.get("order_id"),
        order.get("status"),
        order.get("qty"),
        order.get("fill_price"),
    )

def main():
    con = sqlite3.connect(DB_PATH)
    con.execute(CREATE_TABLE)
    con.commit()

    lines = LOG_PATH.read_text().splitlines()
    imported = skipped = 0

    with con:
        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            row = parse_line(line)
            if row is None:
                print(f"  SKIP line {lineno}: could not parse")
                skipped += 1
                continue
            try:
                con.execute(INSERT, row)
                imported += 1
            except Exception as e:
                print(f"  SKIP line {lineno}: insert error — {e}")
                skipped += 1

    print(f"\nDone. Imported: {imported}  Skipped: {skipped}  Total lines: {len(lines)}")
    print(f"Database: {DB_PATH}")

if __name__ == "__main__":
    main()
