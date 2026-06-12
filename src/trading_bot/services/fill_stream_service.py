"""Alpaca fill stream transport and event handling."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

from alpaca.trading.stream import TradingStream
from market_time import is_market_hours
from runtime_config import get_alpaca_base_url
from services.intraday_trade_feedback_service import IntradayTradeFeedbackService

from repositories import fill_repo

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
RECONNECT_DELAY = 30
DEFAULT_HEARTBEAT_SECONDS = 300


class FillEventHandler:
    def __init__(
        self,
        *,
        repository=fill_repo,
        logger: logging.Logger | None = None,
        feedback_service: IntradayTradeFeedbackService | None = None,
        market_hours_fn=is_market_hours,
    ):
        self.repository = repository
        self.logger = logger or logging.getLogger(__name__)
        self.feedback_service = feedback_service or IntradayTradeFeedbackService()
        self.market_hours_fn = market_hours_fn

    def init_storage(self) -> None:
        self.repository.init_fill_events_table()

    def record_fill_event(self, event, order) -> None:
        """Persist every Alpaca trade_update event for forensic history."""
        try:
            self.repository.record_fill_event(event, order)
        except Exception as e:
            self.logger.error(f"record_fill_event failed: {e}")

    def update_db(
        self,
        order_id: str,
        status: str,
        fill_price: float | None,
        filled_qty: float | None = None,
    ) -> int:
        try:
            return self.repository.update_trade_fill(
                order_id,
                status,
                fill_price,
                filled_qty,
            )
        except Exception as e:
            self.logger.error(f"DB update failed for order {order_id}: {e}")
            return 0

    def trade_order_exists(self, order_id: str) -> bool:
        try:
            return self.repository.trade_order_exists(order_id)
        except Exception as e:
            self.logger.error(f"trade_order_exists failed for order {order_id}: {e}")
            return False

    def insert_synthetic_exit(
        self,
        order_id,
        symbol,
        side,
        status,
        filled_qty,
        fill_price,
        parent_order_id=None,
    ) -> bool:
        """Insert synthetic trade row for unmatched bracket-leg fills."""
        try:
            inserted = self.repository.insert_synthetic_exit(
                order_id=order_id,
                symbol=symbol,
                side=side,
                status=status,
                filled_qty=filled_qty,
                fill_price=fill_price,
                parent_order_id=parent_order_id,
            )
            if not inserted:
                self.logger.info(
                    f"BRACKET EXIT synthetic row skipped: order already recorded "
                    f"{symbol} {side.upper()} order={order_id}"
                )
                return True

            self.logger.info(
                f"BRACKET EXIT synthetic row inserted: {symbol} {side.upper()} "
                f"qty={filled_qty} fill_price={fill_price} order={order_id} parent={parent_order_id}"
            )
            return True
        except Exception as e:
            self.logger.error(f"insert_synthetic_exit failed for {symbol} order={order_id}: {e}")
            return False

    def insert_synthetic_buy_fill(
        self,
        order_id,
        symbol,
        status,
        filled_qty,
        fill_price,
        parent_order_id=None,
    ) -> bool:
        """Insert synthetic trade row for unmatched buy fills.

        A buy fill without a local trade row breaks cost basis and realized P&L.
        This repair path is intentionally idempotent by order_id.
        """
        try:
            inserted = self.repository.insert_synthetic_fill(
                order_id=order_id,
                symbol=symbol,
                side="buy",
                status=status,
                filled_qty=filled_qty,
                fill_price=fill_price,
                parent_order_id=parent_order_id,
            )
            if not inserted:
                self.logger.info(
                    f"BUY FILL synthetic row skipped: order already recorded "
                    f"{symbol} order={order_id}"
                )
                return True

            self.logger.warning(
                f"BUY FILL synthetic row inserted: {symbol} qty={filled_qty} "
                f"fill_price={fill_price} order={order_id} parent={parent_order_id}"
            )
            return True
        except Exception as e:
            self.logger.error(
                f"insert_synthetic_buy_fill failed for {symbol} order={order_id}: {e}"
            )
            return False

    def capture_post_fill_learning(self, *, symbol: str | None, side: str | None) -> None:
        if os.getenv("INTRADAY_POST_FILL_LEARNING_ENABLED", "true").strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            return
        try:
            target_date = datetime.now().strftime("%Y-%m-%d")
            snapshot = self.feedback_service.capture_performance_snapshot(
                target_date,
                phase="post_fill",
                trigger_symbol=symbol,
                include_historical=True,
            )
            self.logger.info(
                "Intraday learning updated after fill: symbol=%s side=%s status=%s "
                "closed_trades=%s avg_pnl_pct=%s evidence_keys=%s",
                symbol,
                side,
                snapshot.get("status"),
                snapshot.get("same_day_closed_trades"),
                snapshot.get("same_day_avg_pnl_pct"),
                snapshot.get("evidence_keys"),
            )
        except Exception as exc:
            self.logger.error("Post-fill intraday learning update failed for %s: %s", symbol, exc)

    async def trade_update_handler(self, data):
        try:
            event = data.event
            order = data.order

            if not self.market_hours_fn():
                return

            self.record_fill_event(event, order)

            order_id = order.get("id")
            symbol = order.get("symbol")
            side = order.get("side")
            filled_qty = order.get("filled_qty")
            status = order.get("status")
            fill_price = order.get("filled_avg_price")
            fill_price = float(fill_price) if fill_price else None

            if event not in ("fill", "partial_fill"):
                self.logger.info(
                    f"Trade event [{event}] {symbol} order={order_id} status={status} "
                    "- no DB update needed"
                )
                return

            rows = self.update_db(order_id, status, fill_price, filled_qty)
            if rows:
                self.logger.info(
                    f"FILL: {symbol} {side.upper()} {filled_qty} shares @ ${fill_price} "
                    f"| status={status} order={order_id}"
                )
                self.capture_post_fill_learning(symbol=symbol, side=side)
            else:
                parent_order_id = order.get("parent_order_id")

                if side == "sell":
                    inserted = self.insert_synthetic_exit(
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        status=status,
                        filled_qty=filled_qty,
                        fill_price=fill_price,
                        parent_order_id=parent_order_id,
                    )
                    if not inserted:
                        self.logger.warning(
                            f"Fill received for order {order_id} ({symbol}) but no matching row in trades.db "
                            f"and synthetic insert failed - fill_price={fill_price} status={status}"
                        )
                    else:
                        self.capture_post_fill_learning(symbol=symbol, side=side)
                else:
                    inserted = self.insert_synthetic_buy_fill(
                        order_id=order_id,
                        symbol=symbol,
                        status=status,
                        filled_qty=filled_qty,
                        fill_price=fill_price,
                        parent_order_id=parent_order_id,
                    )
                    if not inserted:
                        self.logger.warning(
                            f"Unmatched buy fill received for order {order_id} ({symbol}) "
                            f"but synthetic insert failed - fill_price={fill_price} status={status}"
                        )
                    else:
                        self.capture_post_fill_learning(symbol=symbol, side=side)
        except Exception as e:
            self.logger.error(f"Error in trade_update_handler: {e} | raw data: {data}")


class FillStreamService:
    def __init__(
        self,
        *,
        handler: FillEventHandler,
        logger: logging.Logger | None = None,
        stream_cls=TradingStream,
        api_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
        reconnect_delay: int = RECONNECT_DELAY,
        heartbeat_seconds: int | None = None,
        market_hours_fn=is_market_hours,
    ):
        self.handler = handler
        self.logger = logger or logging.getLogger(__name__)
        self.stream_cls = stream_cls
        self.api_key = api_key if api_key is not None else os.environ.get("ALPACA_API_KEY", "")
        self.secret_key = (
            secret_key if secret_key is not None else os.environ.get("ALPACA_SECRET_KEY", "")
        )
        self.base_url = base_url or get_alpaca_base_url()
        self.reconnect_delay = reconnect_delay
        self.heartbeat_seconds = (
            heartbeat_seconds if heartbeat_seconds is not None else _fill_stream_heartbeat_seconds()
        )
        self._heartbeat_started = False
        self.market_hours_fn = market_hours_fn

    @classmethod
    def from_container(cls, container) -> "FillStreamService":
        logger = getattr(container, "logger", None) or logging.getLogger(__name__)
        return cls(
            handler=FillEventHandler(logger=logger),
            logger=logger,
        )

    def run_stream(self) -> None:
        self.logger.info(f"Starting Alpaca trade update stream: base_url={self.base_url}")
        paper = self.base_url.rstrip("/") == PAPER_BASE_URL
        stream = self.stream_cls(
            self.api_key,
            self.secret_key,
            paper=paper,
            url_override=None if paper else self.base_url,
        )
        stream.subscribe_trade_updates(self.handler.trade_update_handler)
        self.logger.info("Trade update stream connected - listening for fills")
        stream.run()

    def start_heartbeat(self) -> None:
        if self._heartbeat_started or self.heartbeat_seconds <= 0:
            return
        self._heartbeat_started = True

        def _heartbeat_loop() -> None:
            while True:
                time.sleep(self.heartbeat_seconds)
                if not self.market_hours_fn():
                    continue
                self.logger.info(
                    "Fill stream heartbeat: process_alive=true base_url=%s",
                    self.base_url,
                )

        threading.Thread(
            target=_heartbeat_loop,
            name="fill-stream-heartbeat",
            daemon=True,
        ).start()

    def run(self) -> None:
        if not self.api_key or not self.secret_key:
            self.logger.error("ALPACA_API_KEY or ALPACA_SECRET_KEY not set - exiting")
            raise SystemExit(1)

        self.start_heartbeat()
        storage_initialized = False

        while True:
            if not self.market_hours_fn():
                time.sleep(self.reconnect_delay)
                continue
            if not storage_initialized:
                self.handler.init_storage()
                storage_initialized = True
            try:
                self.run_stream()
                self.logger.warning(
                    "Stream exited unexpectedly - reconnecting in %ds",
                    self.reconnect_delay,
                )
            except KeyboardInterrupt:
                self.logger.info("Interrupted - shutting down")
                break
            except Exception as e:
                self.logger.error(
                    "Stream error: %s - reconnecting in %ds",
                    e,
                    self.reconnect_delay,
                )
            time.sleep(self.reconnect_delay)


def _fill_stream_heartbeat_seconds() -> int:
    raw = os.environ.get("FILL_STREAM_HEARTBEAT_SECONDS", str(DEFAULT_HEARTBEAT_SECONDS))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_HEARTBEAT_SECONDS
