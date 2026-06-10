"""FIFO trade matching service."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from repositories.trade_matcher_repo import TradeMatcherRepository
from symbols_config import SYMBOL_SIGNAL_SOURCE

MATCH_SOURCE_FIELDS = [
    "signal_source",
    "match_source",
    "entry_source",
    "entry_order_id",
    "exit_order_id",
    "exit_reason",
]

ENTRY_CONTEXT_FIELDS = [
    "macro_regime",
    "risk_multiplier",
    "market_bias",
    "risk_level",
    "entry_quality",
    "trend_direction",
    "trend_strength",
    "momentum_direction",
    "momentum_pct",
    "correlation_cluster",
    "cluster_exposure_pct",
    "market_bias_effective",
    "market_bias_override_reason",
    "fundamental_score",
    "session_trend_label",
    "session_trend_score",
    "session_return_pct",
    "session_momentum_5m_pct",
    "session_momentum_15m_pct",
    "session_momentum_30m_pct",
    "session_distance_from_vwap_pct",
    "session_momentum_reason",
    "prediction_score",
    "prediction_decision",
    "prediction_reason",
    "setup_label",
    "setup_policy_action",
    "setup_policy_reason",
    "setup_confidence_adjustment",
    "setup_size_multiplier",
    "setup_unknown_reason",
    "ml_prediction_score",
    "ml_prediction_bucket",
    "buy_opportunity_score",
    "buy_opportunity_recommendation",
    "buy_opportunity_reason",
]


def parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def row_get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def entry_source_for_row(row) -> str:
    confidence = str(row_get(row, "confidence") or "").lower()
    reason = str(row_get(row, "rejection_reason") or "").lower()
    if confidence == "auto_buy_manager" or reason.startswith("auto_buy_manager:"):
        return "auto_buy_manager"
    return "webhook_buy"


class TradeMatcherService:
    def __init__(
        self,
        *,
        repository: TradeMatcherRepository,
        symbol_signal_source: dict[str, str] | None = None,
    ):
        self.repository = repository
        self.symbol_signal_source = symbol_signal_source or SYMBOL_SIGNAL_SOURCE

    def load_filled_trades(self) -> list[dict[str, Any]]:
        return self.repository.load_filled_trades()

    def match_trades(self):
        rows = self.load_filled_trades()
        open_lots = defaultdict(deque)
        net_qty_by_symbol = defaultdict(float)
        matched = []

        for row in rows:
            symbol = row["symbol"]
            action = row["action"]
            qty = float(row["qty"] or 0)
            price = float(row["fill_price"] or 0)

            if not symbol or qty <= 0 or price <= 0:
                continue

            if action == "buy":
                net_qty_by_symbol[symbol] += qty
            elif action == "sell":
                net_qty_by_symbol[symbol] -= qty

            if action == "buy":
                open_lots[symbol].append(
                    {
                        "timestamp": row["timestamp"],
                        "qty": qty,
                        "price": price,
                        "row": row,
                    }
                )
                continue

            if action == "sell":
                remaining = qty

                while remaining > 0 and open_lots[symbol]:
                    lot = open_lots[symbol][0]
                    matched_qty = min(remaining, lot["qty"])

                    entry_price = lot["price"]
                    exit_price = price
                    pnl = (exit_price - entry_price) * matched_qty
                    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0

                    entry_ts = parse_ts(lot["timestamp"])
                    exit_ts = parse_ts(row["timestamp"])
                    holding_minutes = None
                    if entry_ts and exit_ts:
                        holding_minutes = round(
                            (exit_ts - entry_ts).total_seconds() / 60,
                            2,
                        )

                    entry_row = lot["row"]

                    item = {
                        "symbol": symbol,
                        "entry_timestamp": lot["timestamp"],
                        "exit_timestamp": row["timestamp"],
                        "holding_minutes": holding_minutes,
                        "qty": matched_qty,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "realized_pnl": round(pnl, 2),
                        "realized_pnl_pct": round(pnl_pct, 3),
                        "won": 1 if pnl > 0 else 0,
                    }

                    for field in ENTRY_CONTEXT_FIELDS:
                        item[field] = row_get(entry_row, field)

                    item["match_source"] = "fifo_match"
                    item["entry_source"] = entry_source_for_row(entry_row)
                    item["entry_order_id"] = row_get(entry_row, "order_id")
                    item["exit_order_id"] = row_get(row, "order_id")
                    item["exit_reason"] = row_get(row, "rejection_reason")
                    item["signal_source"] = self.symbol_signal_source.get(
                        symbol,
                        "unknown",
                    )
                    matched.append(item)

                    lot["qty"] -= matched_qty
                    remaining -= matched_qty

                    if lot["qty"] <= 0:
                        open_lots[symbol].popleft()

        synthetic = self._synthetic_position_manager_matches(matched)
        if synthetic:
            matched.extend(synthetic)

        self._reconcile_open_lots_to_net_qty(open_lots, net_qty_by_symbol)
        return matched, open_lots

    @staticmethod
    def _reconcile_open_lots_to_net_qty(open_lots, net_qty_by_symbol) -> None:
        """Keep the open-lot view aligned with net executed quantity.

        Historical data can contain unmatched sell rows, usually synthetic exits
        or partial-fill/cancel broker events whose original entry row was not
        available. FIFO correctly avoids creating short lots, but without this
        reconciliation a later buy can appear open even when net execution
        accounting is flat.
        """

        for symbol, lots in list(open_lots.items()):
            net_qty = max(float(net_qty_by_symbol.get(symbol, 0.0)), 0.0)
            open_qty = sum(float(lot.get("qty") or 0.0) for lot in lots)
            excess = open_qty - net_qty

            while excess > 0 and lots:
                lot = lots[0]
                lot_qty = float(lot.get("qty") or 0.0)
                reduction = min(excess, lot_qty)
                lot["qty"] = lot_qty - reduction
                excess -= reduction
                if float(lot.get("qty") or 0.0) <= 0:
                    lots.popleft()

            if not lots:
                open_lots.pop(symbol, None)

    def _synthetic_position_manager_matches(self, matched):
        synthetic = []
        sells = self.repository.load_position_manager_sells()
        existing_synthetic_order_ids = self.repository.existing_synthetic_order_ids()

        for sell_row in sells:
            order_id = str(sell_row["order_id"] or "")
            if not order_id:
                continue
            if order_id in existing_synthetic_order_ids:
                continue

            normal_match_exists = any(
                trade.get("symbol") == sell_row["symbol"]
                and trade.get("exit_timestamp") == sell_row["timestamp"]
                for trade in matched
            )
            if normal_match_exists:
                continue

            item = self._synthetic_match_from_position_manager_exit(sell_row)
            if item:
                synthetic.append(item)

        return synthetic

    def _synthetic_match_from_position_manager_exit(self, sell_row):
        payload = self.repository.event_payload_for_order(sell_row["order_id"])
        if not payload:
            return None

        decision = payload.get("decision") or {}

        try:
            qty = float(sell_row["qty"] or decision.get("qty") or 0)
            entry_price = float(decision.get("avg_entry") or 0)
            exit_price = float(sell_row["fill_price"] or 0)
        except Exception:
            return None

        if qty <= 0 or entry_price <= 0 or exit_price <= 0:
            return None

        realized_pnl = round((exit_price - entry_price) * qty, 2)
        realized_pnl_pct = round(((exit_price - entry_price) / entry_price) * 100.0, 3)
        won = 1 if realized_pnl > 0 else 0

        return {
            "symbol": sell_row["symbol"],
            "signal_source": self.symbol_signal_source.get(sell_row["symbol"], "unknown"),
            "entry_timestamp": None,
            "exit_timestamp": sell_row["timestamp"],
            "holding_minutes": None,
            "qty": qty,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "won": won,
            "macro_regime": None,
            "risk_multiplier": None,
            "market_bias": None,
            "risk_level": None,
            "entry_quality": None,
            "trend_direction": None,
            "trend_strength": None,
            "momentum_direction": None,
            "momentum_pct": None,
            "correlation_cluster": None,
            "cluster_exposure_pct": None,
            "market_bias_effective": None,
            "market_bias_override_reason": None,
            "fundamental_score": None,
            "session_trend_label": None,
            "session_trend_score": None,
            "session_return_pct": None,
            "session_momentum_5m_pct": decision.get("momentum_5m_pct"),
            "session_momentum_15m_pct": decision.get("momentum_15m_pct"),
            "session_momentum_30m_pct": decision.get("momentum_30m_pct"),
            "session_distance_from_vwap_pct": decision.get("vwap_dist_pct"),
            "session_momentum_reason": None,
            "prediction_score": None,
            "prediction_decision": None,
            "prediction_reason": None,
            "setup_label": None,
            "setup_policy_action": None,
            "setup_policy_reason": None,
            "setup_confidence_adjustment": None,
            "setup_size_multiplier": None,
            "buy_opportunity_score": None,
            "buy_opportunity_recommendation": None,
            "buy_opportunity_reason": None,
            "match_source": "synthetic_position_manager_exit",
            "entry_source": "position_manager_avg_entry",
            "entry_order_id": None,
            "exit_order_id": sell_row["order_id"],
            "exit_reason": sell_row["rejection_reason"],
        }

    def init_matched_trades_table(self) -> None:
        self.repository.init_matched_trades_table()

    def rebuild_matched_trades(self):
        matched, open_lots = self.match_trades()
        self.init_matched_trades_table()

        columns = (
            [
                "symbol",
                "entry_timestamp",
                "exit_timestamp",
                "holding_minutes",
                "qty",
                "entry_price",
                "exit_price",
                "realized_pnl",
                "realized_pnl_pct",
                "won",
            ]
            + ENTRY_CONTEXT_FIELDS
            + MATCH_SOURCE_FIELDS
        )

        self.repository.replace_matched_trades(matched, columns)
        return matched, open_lots


def build_default_trade_matcher_service(db_path=None) -> TradeMatcherService:
    repository = (
        TradeMatcherRepository(db_path=db_path) if db_path is not None else TradeMatcherRepository()
    )
    return TradeMatcherService(repository=repository)
