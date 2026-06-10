"""Runtime trend table state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from services import trend_context_service


class TrendStateService:
    def __init__(
        self,
        *,
        approved_symbols: set[str],
        signal_history: dict[str, list[str]],
        trend_table: dict[str, dict[str, Any]],
        trades_repo: Any,
        market_bias: dict[str, dict[str, Any]],
        symbol_market_alignment_map: dict[str, dict[str, Any]],
        load_market_context: Callable[[], None],
        log: Any,
    ):
        self.approved_symbols = approved_symbols
        self.signal_history = signal_history
        self.trend_table = trend_table
        self.trades_repo = trades_repo
        self.market_bias = market_bias
        self.symbol_market_alignment_map = symbol_market_alignment_map
        self.load_market_context = load_market_context
        self.log = log

    def compute_trend(self, recent_actions: list) -> dict[str, Any]:
        return trend_context_service.compute_trend(recent_actions)

    def build_table(self) -> None:
        """Build trend table for every approved symbol."""
        try:
            for sym in self.approved_symbols:
                self.signal_history.setdefault(sym, [])
                self.trend_table[sym] = {
                    "direction": "neutral",
                    "strength": "weak",
                    "consecutive_count": 0,
                    "last_signal": None,
                    "last_time": None,
                }

            approved = sorted(self.approved_symbols)
            rows = self.trades_repo.recent_signal_history(approved)
            history: dict[str, list[str]] = {}
            last_time: dict[str, Any] = {}

            for sym, act, ts in rows:
                if sym not in self.approved_symbols:
                    continue
                history.setdefault(sym, []).append(act)
                last_time.setdefault(sym, ts)

            for sym in self.approved_symbols:
                actions = history.get(sym, [])
                self.signal_history[sym] = actions[:10]
                entry = self.compute_trend(actions)
                entry["last_time"] = last_time.get(sym)
                self.trend_table[sym] = entry

            self.log.info(
                "Trend table built for "
                f"{len(self.trend_table)}/{len(self.approved_symbols)} approved symbols"
            )
        except Exception as exc:
            self.log.error(f"trend table build failed: {exc}")

    def refresh_signal_history(self, symbol: str) -> None:
        try:
            rows = self.trades_repo.recent_actions_for_trend(symbol)
            self.signal_history[symbol] = [row[0] for row in rows]
        except Exception as exc:
            self.log.warning(f"trend history refresh failed for {symbol}: {exc}")

    def update_history(
        self,
        symbol: str,
        action: str,
        *,
        compute_trend_func: Callable[[list], dict[str, Any]] | None = None,
        refresh_signal_history: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        return trend_context_service.update_signal_trend_history(
            symbol=symbol,
            action=action,
            signal_history=self.signal_history,
            trend_table=self.trend_table,
            refresh_signal_history=refresh_signal_history or self.refresh_signal_history,
            now=datetime.now,
            compute_trend_func=compute_trend_func or self.compute_trend,
            log=self.log,
        )

    def symbol_market_alignment(self, symbol: str) -> dict[str, Any]:
        return trend_context_service.symbol_market_alignment(
            symbol,
            symbol_market_alignment_map=self.symbol_market_alignment_map,
            market_bias=self.market_bias,
            trend_table=self.trend_table,
            signal_history=self.signal_history,
            load_market_context=self.load_market_context,
            refresh_signal_history=self.refresh_signal_history,
        )
