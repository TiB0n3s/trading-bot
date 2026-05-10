import json
import logging
import os
from db import get_connection
import time
from datetime import datetime
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
RECONNECT_DELAY = 30


def init_fill_events_table():
    con = get_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS fill_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event TEXT,
            order_id TEXT,
            parent_order_id TEXT,
            client_order_id TEXT,
            symbol TEXT,
            side TEXT,
            status TEXT,
            filled_qty REAL,
            fill_price REAL,
            raw_json TEXT
        )
    """)
    con.commit()
    con.close()


init_fill_events_table()


def record_fill_event(event, order):
    """Persist every Alpaca trade_update event to fill_events for forensic history.
    Captures every event regardless of whether it matches a trades.db row."""
    try:
        order_id = order.get("id")
        parent_order_id = order.get("parent_order_id")
        client_order_id = order.get("client_order_id")
        symbol = order.get("symbol")
        side = order.get("side")
        status = order.get("status")
        filled_qty = order.get("filled_qty")
        fill_price = order.get("filled_avg_price")

        try:
            raw_json = json.dumps(dict(order))
        except Exception:
            raw_json = str(order)

        con = get_connection()
        con.execute("""
            INSERT INTO fill_events (
                timestamp, event, order_id, parent_order_id, client_order_id,
                symbol, side, status, filled_qty, fill_price, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            event,
            order_id,
            parent_order_id,
            client_order_id,
            symbol,
            side,
            status,
            float(filled_qty) if filled_qty else None,
            float(fill_price) if fill_price else None,
            raw_json,
        ))
        con.commit()
        con.close()
    except Exception as e:
        logger.error(f"record_fill_event failed: {e}")


def update_db(order_id: str, status: str, fill_price: float | None):
    try:
        con = get_connection()
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


def insert_synthetic_exit(order_id, symbol, side, status, filled_qty, fill_price, parent_order_id=None):
    """Insert a synthetic trade row when a fill event has no matching order_id
    in trades.db. Used primarily for bracket-leg sell-side child fills (stop-loss
    or take-profit triggers from bot-submitted bracket buys).

    Note: this does NOT verify that parent_order_id corresponds to a known buy
    — the caller is responsible for restricting calls to side='sell' so we
    don't synthesize random buy rows. The trade_update_handler enforces that.
    """
    try:
        action = "sell" if side == "sell" else "buy"

        con = get_connection()
        con.execute("""
            INSERT INTO trades (
                timestamp, symbol, action, signal_price, approved, rejection_reason,
                confidence, position_size_pct, stop_loss_pct, take_profit_pct,
                order_id, order_status, qty, fill_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            symbol,
            action,
            fill_price,
            1,
            f"synthetic_bracket_exit: parent_order_id={parent_order_id}" if parent_order_id else "synthetic_bracket_exit: parent unknown",
            "n/a",
            0.0,
            0.0,
            0.0,
            order_id,
            status,
            int(float(filled_qty)) if filled_qty else None,
            fill_price,
        ))
        con.commit()
        con.close()
        logger.info(
            f"BRACKET EXIT synthetic row inserted: {symbol} {side.upper()} "
            f"qty={filled_qty} fill_price={fill_price} order={order_id} parent={parent_order_id}"
        )
        return True
    except Exception as e:
        logger.error(f"insert_synthetic_exit failed for {symbol} order={order_id}: {e}")
        return False


async def trade_update_handler(data):
    try:
        event = data.event
        order = data.order

        record_fill_event(event, order)

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
            parent_order_id = order.get("parent_order_id")

            if side == "sell":
                inserted = insert_synthetic_exit(
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    status=status,
                    filled_qty=filled_qty,
                    fill_price=fill_price,
                    parent_order_id=parent_order_id,
                )
                if not inserted:
                    logger.warning(
                        f"Fill received for order {order_id} ({symbol}) but no matching row in trades.db "
                        f"and synthetic insert failed — fill_price={fill_price} status={status}"
                    )
            else:
                logger.warning(
                    f"Unmatched non-sell fill received for order {order_id} ({symbol}) "
                    f"— not inserting synthetic exit row"
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
