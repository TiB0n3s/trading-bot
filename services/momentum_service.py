"""Short-term momentum calculation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


class MomentumService:
    def __init__(
        self,
        *,
        market_data_service: Any,
        iex_thin_symbols: set[str],
        log: Any,
    ):
        self.market_data_service = market_data_service
        self.iex_thin_symbols = iex_thin_symbols
        self.log = log

    def get_momentum(
        self,
        symbol: str,
        price: float,
        premarket_bias: str | None = None,
    ) -> dict[str, Any] | None:
        try:
            start = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
            bars = self.market_data_service.get_bars_with_fallback(
                symbol,
                "1Min",
                start=start,
                feed="sip",
            )

            if len(bars) < 2:
                return None

            bars = bars[-15:]
            first_close = float(bars[0].c)
            last_close = float(bars[-1].c)

            if first_close <= 0 or last_close <= 0:
                return None

            recent_bars = bars[-5:] if len(bars) >= 5 else bars
            short_first = float(recent_bars[0].c)
            short_last = float(recent_bars[-1].c)

            momentum_5m_pct = (short_last - short_first) / short_first * 100
            momentum_15m_pct = (last_close - first_close) / first_close * 100
            price_vs_bars = (
                (price - last_close) / last_close * 100 if last_close > 0 else 0.0
            )

            momentum_acceleration_pct = None
            momentum_state = "insufficient_data"
            if len(bars) >= 5:
                returns = []
                for prev, cur in zip(bars[-5:-1], bars[-4:]):
                    prev_close = float(prev.c)
                    cur_close = float(cur.c)
                    if prev_close > 0:
                        returns.append((cur_close - prev_close) / prev_close * 100)
                if len(returns) >= 4:
                    last_return = returns[-1]
                    prior_avg = sum(returns[:-1]) / len(returns[:-1])
                    momentum_acceleration_pct = last_return - prior_avg
                    if momentum_acceleration_pct > 0.03:
                        momentum_state = "accelerating"
                    elif momentum_acceleration_pct < -0.03:
                        momentum_state = "decelerating"
                    else:
                        momentum_state = "flat"

            volume_surge_ratio = None
            volume_state = "insufficient_data"
            if len(bars) >= 11:
                current_volume = float(getattr(bars[-1], "v", 0) or 0)
                prior_volumes = [float(getattr(b, "v", 0) or 0) for b in bars[-11:-1]]
                usable_volumes = [v for v in prior_volumes if v > 0]
                if usable_volumes:
                    avg_volume = sum(usable_volumes) / len(usable_volumes)
                    if avg_volume > 0:
                        volume_surge_ratio = current_volume / avg_volume
                        if volume_surge_ratio >= 2.0:
                            volume_state = "surge"
                        elif volume_surge_ratio >= 1.5:
                            volume_state = "elevated"
                        elif volume_surge_ratio < 0.8:
                            volume_state = "thin"
                        else:
                            volume_state = "normal"

            if momentum_5m_pct > 0.1:
                direction = "rising"
            elif momentum_5m_pct < -0.1:
                direction = "falling"
            else:
                direction = "flat"

            alignment = "neutral"
            action_hint = "normal"

            if premarket_bias == "buy":
                if momentum_5m_pct > 0.10 and momentum_15m_pct > 0.15:
                    alignment = "confirmed"
                    action_hint = "favor_approval"
                elif momentum_5m_pct < -0.15 and momentum_15m_pct < -0.25:
                    alignment = "contradicted"
                    action_hint = "downgrade_or_reject"
                else:
                    alignment = "mixed"
                    action_hint = "caution"

            elif premarket_bias == "avoid":
                if momentum_5m_pct > 0.20 and momentum_15m_pct > 0.30:
                    alignment = "tape_strength_against_avoid"
                    action_hint = "still_respect_avoid_gate"
                else:
                    alignment = "avoid_confirmed"
                    action_hint = "avoid"

            elif premarket_bias == "neutral":
                if momentum_5m_pct > 0.15 and momentum_15m_pct > 0.25:
                    alignment = "bullish_intraday_shift"
                    action_hint = "watch_only_unless_trend_confirms"
                elif momentum_5m_pct < -0.15 and momentum_15m_pct < -0.25:
                    alignment = "bearish_intraday_shift"
                    action_hint = "caution"
                else:
                    alignment = "neutral"
                    action_hint = "normal"

            return {
                "direction": direction,
                "momentum_pct": round(momentum_5m_pct, 3),
                "momentum_5m_pct": round(momentum_5m_pct, 3),
                "momentum_15m_pct": round(momentum_15m_pct, 3),
                "momentum_acceleration_pct": round(momentum_acceleration_pct, 4)
                if momentum_acceleration_pct is not None
                else None,
                "momentum_state": momentum_state,
                "volume_surge_ratio": round(volume_surge_ratio, 3)
                if volume_surge_ratio is not None
                else None,
                "volume_state": volume_state,
                "volume_note": "iex_thin" if symbol in self.iex_thin_symbols else None,
                "price_vs_bars": round(price_vs_bars, 3),
                "bar_count": len(bars),
                "last_close": round(last_close, 4),
                "premarket_bias": premarket_bias,
                "premarket_alignment": alignment,
                "action_hint": action_hint,
            }

        except Exception as exc:
            self.log.warning(f"get_momentum failed for {symbol}: {exc}")
            return None
