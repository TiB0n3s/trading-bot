"""Runtime market-context cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from risk.macro_policy import DEFAULT_MACRO_POLICY, policy_from_market_context


class MarketContextService:
    def __init__(
        self,
        *,
        path: Path,
        market_bias: dict[str, dict[str, Any]],
        expected_market_context_date: Callable[[], Any],
        log: Any,
    ):
        self.path = path
        self.market_bias = market_bias
        self.expected_market_context_date = expected_market_context_date
        self.log = log
        self.mtime = 0.0
        self.context: dict[str, Any] = {}
        self.context_status: str = "not_loaded"

    def load(self) -> None:
        """Load same-day pre-market research into the shared market-bias dict."""
        if not self.path.exists():
            return

        try:
            current_mtime = self.path.stat().st_mtime
            if current_mtime <= self.mtime:
                return
            self.mtime = current_mtime

            ctx = json.loads(self.path.read_text())
            market_date = ctx.get("market_date")
            expected_date = self.expected_market_context_date().isoformat()
            self.market_bias.clear()
            self.context = {}
            if market_date != expected_date:
                self.context_status = "stale"
                self.log.warning(
                    "market_context.json is stale "
                    f"(market_date={market_date}, expected={expected_date}) — "
                    "cleared market bias"
                )
                return

            self.context = ctx
            self.context_status = "loaded"
            symbols = ctx.get("symbols") or {}
            for sym, entry in symbols.items():
                if isinstance(entry, dict) and entry.get("bias") in (
                    "buy",
                    "avoid",
                    "neutral",
                ):
                    enriched_entry = dict(entry)
                    enriched_entry.setdefault("bias", entry["bias"])
                    enriched_entry.setdefault("reason", "")
                    enriched_entry.setdefault("confidence", "")
                    enriched_entry.setdefault("fundamental_score", None)
                    enriched_entry.setdefault("risk_level", None)
                    enriched_entry.setdefault("entry_quality", None)
                    enriched_entry.setdefault("avoid_type", None)
                    self.market_bias[sym] = enriched_entry

            avoid_count = sum(1 for value in self.market_bias.values() if value["bias"] == "avoid")
            buy_count = sum(1 for value in self.market_bias.values() if value["bias"] == "buy")
            neutral_count = sum(
                1 for value in self.market_bias.values() if value["bias"] == "neutral"
            )
            macro = ctx.get("macro_sentiment", "unknown")
            self.log.info(
                f"Market bias loaded for {len(self.market_bias)} symbols "
                f"(buy={buy_count}, avoid={avoid_count}, neutral={neutral_count}, "
                f"macro={macro})"
            )
        except Exception as exc:
            self.context = {}
            self.context_status = "error"
            self.log.error(f"market context load failed: {exc}")

    def file_summary(self) -> tuple[str | None, str | None]:
        """Return market_context.json date and macro sentiment for status payloads."""
        if not self.path.exists():
            return None, None
        ctx = json.loads(self.path.read_text())
        return ctx.get("market_date"), ctx.get("macro_sentiment")

    def macro_risk(self) -> dict[str, Any]:
        """Return same-day macro policy from the loaded canonical context."""
        self.load()
        if not self.context:
            if self.context_status == "stale":
                return {
                    **DEFAULT_MACRO_POLICY,
                    "macro_regime": "stale",
                    "risk_multiplier": 0.75,
                    "max_new_positions": 8,
                    "block_new_buys": False,
                    "reason": "market_context.json stale; using caution defaults",
                }
            return {
                **DEFAULT_MACRO_POLICY,
                "macro_regime": "unknown",
                "risk_multiplier": 0.75,
                "max_new_positions": 8,
                "block_new_buys": False,
                "reason": "market_context.json unavailable; using caution defaults",
            }
        return policy_from_market_context(self.context)
