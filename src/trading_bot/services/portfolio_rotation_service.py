"""Portfolio rotation helpers."""

from __future__ import annotations

from typing import Any, Callable

from services.policies import execution_policy


class PortfolioRotationService:
    def __init__(
        self,
        *,
        broker_service: Any,
        trades_repo: Any,
        trend_table: dict[str, Any],
        market_bias: dict[str, Any],
        open_entry_context: Callable[[str], dict[str, Any] | None],
        log_trade: Callable[..., Any],
        last_order: dict,
        write_cooldown: Callable[..., Any],
        last_sell: dict,
        write_recent_sell: Callable[..., Any],
        enabled: bool,
        max_per_day: int,
        min_candidate_score: int,
        min_hold_minutes: int,
        max_weak_plpc: float,
        excluded_symbols: set[str],
        allowed_risk_levels: set[str],
        allowed_entry_qualities: set[str],
        log: Any,
    ):
        self.broker_service = broker_service
        self.trades_repo = trades_repo
        self.trend_table = trend_table
        self.market_bias = market_bias
        self.open_entry_context = open_entry_context
        self.log_trade = log_trade
        self.last_order = last_order
        self.write_cooldown = write_cooldown
        self.last_sell = last_sell
        self.write_recent_sell = write_recent_sell
        self.enabled = enabled
        self.max_per_day = max_per_day
        self.min_candidate_score = min_candidate_score
        self.min_hold_minutes = min_hold_minutes
        self.max_weak_plpc = max_weak_plpc
        self.excluded_symbols = excluded_symbols
        self.allowed_risk_levels = allowed_risk_levels
        self.allowed_entry_qualities = allowed_entry_qualities
        self.log = log

    def count_today(self) -> int:
        try:
            return self.trades_repo.portfolio_rotation_count_today()
        except Exception as exc:
            self.log.error(f"portfolio rotation count failed: {exc}")
            return 999

    def candidate_score(self, symbol: str, account_state: dict[str, Any]):
        score = 0
        reasons = []
        trend = self.trend_table.get(symbol) or {}
        direction = trend.get("direction")
        strength = trend.get("strength")

        if direction == "bullish" and strength == "confirmed":
            score += 8
            reasons.append("bullish/confirmed")
        elif direction == "bullish" and strength == "developing":
            score += 6
            reasons.append("bullish/developing")
        else:
            return 0, f"trend not eligible ({direction}/{strength})"

        bias = self.market_bias.get(symbol) or {}
        market_bias = bias.get("bias")
        risk_level = (bias.get("risk_level") or "medium").lower()
        entry_quality = (bias.get("entry_quality") or "").lower()

        if market_bias == "avoid":
            return 0, "market_bias=avoid"

        if market_bias == "buy":
            score += 3
            reasons.append("buy bias")
        elif market_bias == "neutral":
            score += 1
            reasons.append("neutral bias")

        if risk_level not in self.allowed_risk_levels:
            return 0, f"risk_level={risk_level} not allowed"
        score += 2
        reasons.append(f"risk={risk_level}")

        if entry_quality not in self.allowed_entry_qualities:
            return 0, f"entry_quality={entry_quality or 'missing'} not allowed"
        score += 3
        reasons.append(f"entry={entry_quality}")

        momentum = account_state.get("momentum") or {}
        if momentum.get("direction") == "rising":
            score += 2
            reasons.append("rising momentum")
        elif momentum.get("direction") == "falling":
            score -= 2
            reasons.append("falling momentum")

        return score, ", ".join(reasons)

    def weakest_rotation_holding(self, candidate_symbol: str):
        try:
            positions = self.broker_service.list_positions()
        except Exception as exc:
            self.log.error(f"weakest rotation holding fetch failed: {exc}")
            return None

        candidates = []
        for pos in positions:
            try:
                sym = str(pos.symbol).upper()
                if sym == candidate_symbol or sym in self.excluded_symbols:
                    continue

                qty = float(pos.qty)
                if qty <= 0:
                    continue

                plpc = float(pos.unrealized_plpc) * 100.0
                current_price = float(pos.current_price)
                entry_ctx = self.open_entry_context(sym) or {}
                holding_minutes = entry_ctx.get("holding_minutes")

                if holding_minutes is not None and holding_minutes < self.min_hold_minutes:
                    continue
                if plpc > self.max_weak_plpc:
                    continue

                trend = self.trend_table.get(sym) or {}
                candidates.append(
                    {
                        "symbol": sym,
                        "qty": qty,
                        "current_price": current_price,
                        "unrealized_plpc": round(plpc, 3),
                        "trend_direction": trend.get("direction"),
                        "trend_strength": trend.get("strength"),
                        "holding_minutes": holding_minutes,
                    }
                )
            except Exception as exc:
                self.log.warning(f"weakest rotation holding skipped position: {exc}")

        if not candidates:
            return None

        return sorted(
            candidates,
            key=lambda item: (
                item["unrealized_plpc"],
                item["holding_minutes"] if item["holding_minutes"] is not None else 999999,
            ),
        )[0]

    def try_rotation(self, candidate_symbol, candidate_price, account_state, now_dt):
        return execution_policy.try_portfolio_rotation(
            candidate_symbol=candidate_symbol,
            candidate_price=candidate_price,
            account_state=account_state,
            now_dt=now_dt,
            enabled=self.enabled,
            max_per_day=self.max_per_day,
            min_candidate_score=self.min_candidate_score,
            rotation_count_today=self.count_today,
            rotation_candidate_score=self.candidate_score,
            weakest_rotation_holding=self.weakest_rotation_holding,
            place_order=self.broker_service.place_order,
            log_trade=self.log_trade,
            last_order=self.last_order,
            write_cooldown=self.write_cooldown,
            last_sell=self.last_sell,
            write_recent_sell=self.write_recent_sell,
            logger=self.log,
        )

    def weakest_position_context(self, account_state: dict[str, Any]):
        positions = account_state.get("open_positions") or account_state.get("positions") or []
        weakest = None
        for position in positions:
            try:
                symbol = position.get("symbol")
                unrealized_plpc = float(
                    position.get("unrealized_plpc")
                    or position.get("unrealized_pl_pct")
                    or position.get("unrealized_plpc_pct")
                    or 0
                )
                market_value = float(position.get("market_value") or 0)
                item = {
                    "symbol": symbol,
                    "unrealized_plpc": unrealized_plpc,
                    "market_value": market_value,
                    "weakness_score": unrealized_plpc,
                }
                if weakest is None or item["weakness_score"] < weakest["weakness_score"]:
                    weakest = item
            except Exception:
                continue
        return weakest
