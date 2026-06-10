"""Excursion analysis service for matched trades."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytz
from repositories.excursion_repo import ExcursionRepository
from services.market_data_service import market_data_service

ET = pytz.timezone("America/New_York")


def parse_ts(ts):
    if not ts:
        return None

    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = ET.localize(dt)

    return dt.astimezone(timezone.utc)


def pct_change(start_price, end_price):
    if not start_price or not end_price or start_price <= 0:
        return None
    return (end_price - start_price) / start_price * 100.0


def classify_trade(row, mfe_pct, mae_pct, giveback_pct):
    pnl = float(row["realized_pnl"] or 0)

    if mfe_pct is None or mae_pct is None:
        return "insufficient_data"

    if pnl < 0 and mfe_pct < 0.25:
        return "bad_entry_never_worked"

    if pnl < 0 and mfe_pct >= 0.50:
        return "winner_became_loser"

    if pnl > 0 and giveback_pct is not None and giveback_pct >= 50:
        return "profit_giveback"

    if pnl > 0 and mfe_pct >= 0.75:
        return "good_trade"

    if mae_pct <= -1.0:
        return "large_adverse_excursion"

    return "mixed"


class ExcursionService:
    def __init__(
        self,
        *,
        repository: ExcursionRepository,
        market_data=market_data_service,
    ):
        self.repository = repository
        self.market_data = market_data

    def load_matched_trades(
        self,
        target_date: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.repository.load_matched_trades(target_date, symbol, limit)

    def fetch_trade_bars(self, symbol, entry_ts_utc, exit_ts_utc):
        start = entry_ts_utc.isoformat()
        end = exit_ts_utc.isoformat()

        bars = self.market_data.get_bars_with_fallback(
            symbol,
            "1Min",
            start=start,
            end=end,
            feed="iex",
        )
        out = []

        for bar in bars:
            bar_time = bar.t
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            else:
                bar_time = bar_time.astimezone(timezone.utc)

            out.append(
                {
                    "timestamp": bar_time,
                    "open": float(bar.o),
                    "high": float(bar.h),
                    "low": float(bar.l),
                    "close": float(bar.c),
                }
            )

        return out

    def analyze_trade(self, row):
        symbol = row["symbol"]
        entry_price = float(row["entry_price"] or 0)
        exit_price = float(row["exit_price"] or 0)
        qty = float(row["qty"] or 0)

        entry_ts = parse_ts(row["entry_timestamp"])
        exit_ts = parse_ts(row["exit_timestamp"])

        result = {
            "id": row["id"],
            "symbol": symbol,
            "entry_timestamp": row["entry_timestamp"],
            "exit_timestamp": row["exit_timestamp"],
            "holding_minutes": row["holding_minutes"],
            "qty": qty,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "realized_pnl": float(row["realized_pnl"] or 0),
            "realized_pnl_pct": float(row["realized_pnl_pct"] or 0),
            "market_bias": row["market_bias"],
            "market_bias_effective": row["market_bias_effective"],
            "trend_direction": row["trend_direction"],
            "trend_strength": row["trend_strength"],
            "session_trend_label": row["session_trend_label"],
            "prediction_decision": row["prediction_decision"],
            "setup_label": row["setup_label"],
            "setup_policy_action": row["setup_policy_action"],
            "buy_opportunity_recommendation": row["buy_opportunity_recommendation"],
            "error": None,
        }

        if not symbol or entry_price <= 0 or exit_price <= 0 or not entry_ts or not exit_ts:
            result["error"] = "invalid symbol, prices, or timestamps"
            return result

        if exit_ts <= entry_ts:
            result["error"] = "exit timestamp is not after entry timestamp"
            return result

        try:
            bars = self.fetch_trade_bars(symbol, entry_ts, exit_ts)
        except Exception as e:
            result["error"] = f"bar fetch failed: {e}"
            return result

        if not bars:
            result["error"] = "no bars returned for trade window"
            return result

        highs = [bar["high"] for bar in bars]
        lows = [bar["low"] for bar in bars]

        max_high = max(highs)
        min_low = min(lows)

        mfe_pct = pct_change(entry_price, max_high)
        mae_pct = pct_change(entry_price, min_low)

        mfe_dollars = (max_high - entry_price) * qty
        mae_dollars = (min_low - entry_price) * qty

        realized_pnl = float(row["realized_pnl"] or 0)

        giveback_dollars = None
        giveback_pct = None

        if mfe_dollars > 0:
            giveback_dollars = mfe_dollars - realized_pnl
            giveback_pct = giveback_dollars / mfe_dollars * 100.0

        result.update(
            {
                "mfe_pct": round(mfe_pct, 3) if mfe_pct is not None else None,
                "mae_pct": round(mae_pct, 3) if mae_pct is not None else None,
                "mfe_dollars": round(mfe_dollars, 2),
                "mae_dollars": round(mae_dollars, 2),
                "max_high": round(max_high, 4),
                "min_low": round(min_low, 4),
                "profit_giveback_dollars": (
                    round(giveback_dollars, 2) if giveback_dollars is not None else None
                ),
                "profit_giveback_pct": (
                    round(giveback_pct, 1) if giveback_pct is not None else None
                ),
                "bar_count": len(bars),
            }
        )

        result["excursion_classification"] = classify_trade(
            row,
            result["mfe_pct"],
            result["mae_pct"],
            result["profit_giveback_pct"],
        )

        return result

    def analyze_trades(
        self,
        *,
        target_date: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows = self.load_matched_trades(target_date, symbol, limit)
        return rows, [self.analyze_trade(row) for row in rows]


def build_default_excursion_service(db_path=None) -> ExcursionService:
    repository = (
        ExcursionRepository(db_path=db_path) if db_path is not None else ExcursionRepository()
    )
    return ExcursionService(repository=repository)
