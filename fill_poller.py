import sqlite3
import logging
from pathlib import Path
from broker import api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "trades.db"

PENDING_STATUSES = ("pending_new", "new", "partially_filled")

def poll_fills():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        "SELECT id, order_id, symbol FROM trades WHERE order_status IN (?, ?, ?)",
        PENDING_STATUSES
    ).fetchall()

    checked = updated = skipped = 0

    for row in rows:
        checked += 1
        try:
            order = api.get_order(row["order_id"])
            new_status = order.status
            fill_price = float(order.filled_avg_price) if order.filled_avg_price else None

            cur = con.execute(
                "SELECT order_status, fill_price FROM trades WHERE id = ?", (row["id"],)
            ).fetchone()

            if cur["order_status"] == new_status and cur["fill_price"] == fill_price:
                skipped += 1
                continue

            con.execute(
                "UPDATE trades SET order_status = ?, fill_price = ? WHERE id = ?",
                (new_status, fill_price, row["id"])
            )
            con.commit()
            updated += 1
            logger.info(
                f"Updated {row['symbol']} order {row['order_id']}: "
                f"status={new_status} fill_price={fill_price}"
            )
        except Exception as e:
            logger.error(f"Failed to poll order {row['order_id']} ({row['symbol']}): {e}")
            skipped += 1

    con.close()
    logger.info(f"Poll complete — checked: {checked}, updated: {updated}, skipped: {skipped}")

if __name__ == "__main__":
    poll_fills()
