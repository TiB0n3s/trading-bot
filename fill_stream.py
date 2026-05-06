import logging
import os
import sqlite3
import time
from pathlib import Path

from alpaca_trade_api.stream import Stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "fill_stream.log"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

ALPACA_API_KEY  = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
PAPER_BASE_URL  = "https://paper-api.alpaca.markets"
DB_PATH = Path(__file__).parent / "trades.db"
RECONNECT_DELAY = 30


def update_db(order_id: str, status: str, fill_price: float | None):
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.execute(
            "UPDATE trades SET order_status = ?, fill_price = ? WHERE order_id = ?",
            (status, fill_price, order_id)
        )
        con.commit()
        con.close()
        return cur.rowcount
    except Exception as e:
        logger.error(f"DB update failed for order {order_id}: {e}")
        return 0


async def trade_update_handler(data):
    try:
        event = data.event
        order = data.order

        order_id   = order.get("id")
        symbol     = order.get("symbol")
        side       = order.get("side")
        filled_qty = order.get("filled_qty")
        status     = order.get("status")
        fill_price = order.get("filled_avg_price")
        fill_price = float(fill_price) if fill_price else None

        if event not in ("fill", "partial_fill"):
            logger.info(f"Trade event [{event}] {symbol} order={order_id} status={status} — no DB update needed")
            return

        rows = update_db(order_id, status, fill_price)
        if rows:
            logger.info(
                f"FILL: {symbol} {side.upper()} {filled_qty} shares @ ${fill_price} "
                f"| status={status} order={order_id}"
            )
        else:
            logger.warning(
                f"Fill received for order {order_id} ({symbol}) but no matching row in trades.db "
                f"— fill_price={fill_price} status={status}"
            )
    except Exception as e:
        logger.error(f"Error in trade_update_handler: {e} | raw data: {data}")


def run_stream():
    stream = Stream(
        ALPACA_API_KEY,
        ALPACA_SECRET_KEY,
        base_url=PAPER_BASE_URL,
        data_feed="iex",
    )
    stream.subscribe_trade_updates(trade_update_handler)
    logger.info("Trade update stream connected — listening for fills")
    stream.run()


def main():
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.error("ALPACA_API_KEY or ALPACA_SECRET_KEY not set — exiting")
        raise SystemExit(1)

    while True:
        try:
            run_stream()
            # run() only returns normally on KeyboardInterrupt; treat any return as unexpected
            logger.warning("Stream exited unexpectedly — reconnecting in %ds", RECONNECT_DELAY)
        except KeyboardInterrupt:
            logger.info("Interrupted — shutting down")
            break
        except Exception as e:
            logger.error("Stream error: %s — reconnecting in %ds", e, RECONNECT_DELAY)
        time.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    main()
