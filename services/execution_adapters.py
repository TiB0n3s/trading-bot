"""Execution-adjacent quote and safety adapters."""

from __future__ import annotations

import time
from typing import Any

from services.policies import execution_policy


def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class ExecutionAdapterService:
    def __init__(
        self,
        *,
        market_data_service: Any,
        broker_service: Any,
        symbol_max_spread_pct: dict[str, float],
        max_bid_ask_spread_pct: float,
        max_signal_price_drift_pct: float,
        log: Any,
    ):
        self.market_data_service = market_data_service
        self.broker_service = broker_service
        self.symbol_max_spread_pct = symbol_max_spread_pct
        self.max_bid_ask_spread_pct = max_bid_ask_spread_pct
        self.max_signal_price_drift_pct = max_signal_price_drift_pct
        self.log = log

    def compute_spread_pct(self, bid, ask):
        bid_f = safe_float(bid)
        ask_f = safe_float(ask)

        if bid_f is None or ask_f is None:
            return None
        if bid_f <= 0 or ask_f <= 0:
            return None
        if ask_f <= bid_f:
            return 0.0

        mid = (bid_f + ask_f) / 2.0
        if mid <= 0:
            return None

        return ((ask_f - bid_f) / mid) * 100.0

    def fetch_quote_snapshot(self, symbol):
        quote = self.market_data_service.get_latest_quote(symbol)
        bid = getattr(quote, "bid_price", None)
        ask = getattr(quote, "ask_price", None)
        return {
            "bid": safe_float(bid),
            "ask": safe_float(ask),
            "spread_pct": self.compute_spread_pct(bid, ask),
        }

    def latest_trade_price(self, symbol):
        latest_trade = self.market_data_service.get_latest_trade(symbol)
        return float(latest_trade.price)

    def validate_spread_with_retry(
        self,
        symbol,
        max_spread_pct=0.10,
        suspect_spread_pct=2.00,
        retry_count=3,
        retry_delay_sec=0.35,
    ):
        last = {
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "attempts": 0,
            "suspect_quote": False,
            "ok": False,
            "reason": "second_look: quote unavailable",
        }

        total_attempts = max(1, retry_count)

        for attempt in range(1, total_attempts + 1):
            snap = self.fetch_quote_snapshot(symbol)
            spread_pct = snap["spread_pct"]
            last.update(
                {
                    "bid": snap["bid"],
                    "ask": snap["ask"],
                    "spread_pct": spread_pct,
                    "attempts": attempt,
                }
            )

            if spread_pct is None:
                if attempt < total_attempts:
                    time.sleep(retry_delay_sec)
                    continue
                last["reason"] = "second_look: quote unavailable"
                return last

            if spread_pct <= max_spread_pct:
                last["ok"] = True
                last["reason"] = None
                return last

            if spread_pct > suspect_spread_pct:
                last["suspect_quote"] = True
                if attempt < total_attempts:
                    self.log.warning(
                        f"Second-look suspect quote for {symbol}: "
                        f"spread {spread_pct:.3f}% on attempt {attempt}/{total_attempts} "
                        f"(bid={snap['bid']:.4f}, ask={snap['ask']:.4f}) — retrying"
                    )
                    time.sleep(retry_delay_sec)
                    continue

                last["reason"] = (
                    f"second_look: suspect quote persisted after {attempt} attempts; "
                    f"bid/ask spread {spread_pct:.3f}% exceeds suspect threshold "
                    f"{suspect_spread_pct:.3f}% "
                    f"(bid={snap['bid']:.4f}, ask={snap['ask']:.4f})"
                )
                return last

            last["reason"] = (
                f"second_look: bid/ask spread {spread_pct:.3f}% exceeds max "
                f"{max_spread_pct:.3f}% "
                f"(bid={snap['bid']:.4f}, ask={snap['ask']:.4f})"
            )
            return last

        return last

    def pre_order_safety_check(self, symbol, action, signal_price, account_state):
        return execution_policy.pre_order_safety_check(
            symbol=symbol,
            action=action,
            signal_price=signal_price,
            account_state=account_state,
            latest_trade_price=self.latest_trade_price,
            broker_service=self.broker_service,
            validate_spread_with_retry=self.validate_spread_with_retry,
            symbol_max_spread_pct=self.symbol_max_spread_pct,
            max_bid_ask_spread_pct=self.max_bid_ask_spread_pct,
            max_signal_price_drift_pct=self.max_signal_price_drift_pct,
            logger=self.log,
        )
