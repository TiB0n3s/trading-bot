"""Execution-adjacent policy.

Owns pre-order safety checks and portfolio rotation orchestration decisions.
The functions here delegate side effects through injected dependencies so the
policy surface can be tested without Flask or route code.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from services.policy_controls import policy_family_enabled


def pre_order_safety_check(
    *,
    symbol: str,
    action: str,
    signal_price: Any,
    account_state: dict[str, Any],
    latest_trade_price: Callable[[str], float],
    broker_service,
    validate_spread_with_retry: Callable[..., dict[str, Any]],
    symbol_max_spread_pct: dict[str, float],
    max_bid_ask_spread_pct: float,
    max_signal_price_drift_pct: float,
    logger: logging.Logger,
) -> tuple[bool, str]:
    """Final broker-adjacent safety check immediately before order placement."""
    if not policy_family_enabled("execution"):
        return True, "execution_policy_disabled"

    if action != "buy":
        return True, "sell signal bypasses buy-side second-look checks"

    try:
        latest_price = float(latest_trade_price(symbol))
    except Exception as exc:
        return False, f"failed to fetch latest trade for second-look check: {exc}"

    try:
        signal_price_f = float(signal_price)
    except (TypeError, ValueError):
        return False, f"invalid signal_price for second-look check: {signal_price!r}"

    if signal_price_f <= 0 or latest_price <= 0:
        return False, f"invalid price values signal={signal_price_f} latest={latest_price}"

    drift_pct = abs(latest_price - signal_price_f) / signal_price_f * 100
    if drift_pct > max_signal_price_drift_pct:
        return (
            False,
            f"latest price drift {drift_pct:.3f}% exceeds max {max_signal_price_drift_pct:.3f}% "
            f"(signal={signal_price_f:.4f}, latest={latest_price:.4f})",
        )

    try:
        open_orders = broker_service.list_open_orders(symbol)
        if open_orders:
            return False, f"open broker order already exists for {symbol}"
    except Exception as exc:
        return False, f"failed to check open orders for {symbol}: {exc}"

    try:
        spread_check = validate_spread_with_retry(
            symbol,
            max_spread_pct=symbol_max_spread_pct.get(symbol, max_bid_ask_spread_pct),
            suspect_spread_pct=2.00,
            retry_count=3,
            retry_delay_sec=0.35,
        )

        if not spread_check.get("ok"):
            bid = spread_check.get("bid")
            ask = spread_check.get("ask")
            spread_pct = spread_check.get("spread_pct")
            reason = spread_check.get("reason", "spread check failed")

            try:
                bid_f = float(bid) if bid is not None else None
                ask_f = float(ask) if ask is not None else None
            except (TypeError, ValueError):
                bid_f = None
                ask_f = None

            if action == "buy" and ask_f and ask_f > 0:
                ask_vs_signal_pct = abs(ask_f - signal_price_f) / signal_price_f * 100
                ask_vs_latest_pct = abs(ask_f - latest_price) / latest_price * 100

                if (
                    spread_pct is not None
                    and spread_pct > 2.0
                    and ask_vs_signal_pct <= max_signal_price_drift_pct
                    and ask_vs_latest_pct <= max_signal_price_drift_pct
                ):
                    logger.warning(
                        f"Second-look stale-bid exception for {symbol} BUY: "
                        f"spread={spread_pct:.3f}% but ask is sane "
                        f"(bid={bid_f if bid_f is not None else 'n/a'}, "
                        f"ask={ask_f:.4f}, signal={signal_price_f:.4f}, "
                        f"latest={latest_price:.4f}, ask_vs_signal={ask_vs_signal_pct:.3f}%, "
                        f"ask_vs_latest={ask_vs_latest_pct:.3f}%)"
                    )
                else:
                    return False, reason
            else:
                return False, reason
    except AttributeError as exc:
        logger.warning(f"Second-look quote check unsupported for {symbol}: {exc}")
        account_state["second_look"] = {
            "latest_price": round(latest_price, 4),
            "price_drift_pct": round(drift_pct, 4),
            "quote_check": "unsupported",
        }
    except Exception as exc:
        return True, f"spread check unavailable; fail-open: {exc}"

    return True, "second-look checks passed"


def try_portfolio_rotation(
    *,
    candidate_symbol: str,
    candidate_price: float,
    account_state: dict[str, Any],
    now_dt,
    enabled: bool,
    max_per_day: int,
    min_candidate_score: float,
    rotation_count_today: Callable[[], int],
    rotation_candidate_score: Callable[[str, dict[str, Any]], tuple[float, str]],
    weakest_rotation_holding: Callable[[str], dict[str, Any] | None],
    place_order: Callable[..., dict[str, Any] | None],
    log_trade: Callable[..., None],
    last_order: dict,
    write_cooldown: Callable[[str, str, Any], None],
    last_sell: dict,
    write_recent_sell: Callable[[str, Any, float], None],
    logger: logging.Logger,
) -> tuple[bool, str, dict[str, Any]]:
    """Sell weakest eligible holding to free room for a stronger capped BUY."""
    if not policy_family_enabled("execution"):
        return False, "execution_policy_disabled", {}

    if not enabled:
        return False, "portfolio rotation disabled", {}

    rotations_today = rotation_count_today()
    if rotations_today >= max_per_day:
        return False, f"daily rotation limit reached ({rotations_today}/{max_per_day})", {}

    score, score_reason = rotation_candidate_score(candidate_symbol, account_state)
    if score < min_candidate_score:
        return False, f"candidate score {score} < {min_candidate_score}: {score_reason}", {
            "candidate_score": score,
            "candidate_score_reason": score_reason,
        }

    weakest = weakest_rotation_holding(candidate_symbol)
    if not weakest:
        return False, "no eligible weak holding found", {
            "candidate_score": score,
            "candidate_score_reason": score_reason,
        }

    sell_symbol = weakest["symbol"]
    client_order_id = (
        f"rotate-sell-{sell_symbol.lower()}-{candidate_symbol.lower()}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    )

    logger.warning(
        f"PORTFOLIO ROTATION triggered: candidate={candidate_symbol} score={score} "
        f"reason={score_reason}; selling weakest={sell_symbol} "
        f"plpc={weakest['unrealized_plpc']}% "
        f"trend={weakest['trend_direction']}/{weakest['trend_strength']}"
    )

    order_result = place_order(
        symbol=sell_symbol,
        action="sell",
        position_size_pct=0.0,
        stop_loss_pct=0.0,
        take_profit_pct=0.0,
        risk_level=None,
        client_order_id=client_order_id,
    )

    if not order_result:
        return False, f"rotation sell failed for {sell_symbol}", {
            "candidate_score": score,
            "candidate_score_reason": score_reason,
            "weakest": weakest,
        }

    decision = {
        "approved": True,
        "reason": (
            f"portfolio_rotation: sold {sell_symbol} to free slot for "
            f"{candidate_symbol} score={score}"
        ),
        "position_size_pct": 0.0,
        "stop_loss_pct": 0.0,
        "take_profit_pct": 0.0,
        "confidence": "rotation",
    }
    signal = {
        "symbol": sell_symbol,
        "action": "sell",
        "price": weakest["current_price"],
        "source": "portfolio_rotation",
        "rotation_candidate": candidate_symbol,
        "rotation_candidate_price": candidate_price,
    }

    log_trade(signal, decision, order_result, account_state=account_state)
    last_order[(sell_symbol, "sell")] = now_dt
    write_cooldown(sell_symbol, "sell", now_dt)
    last_sell[sell_symbol] = (now_dt, weakest["current_price"])
    write_recent_sell(sell_symbol, now_dt, weakest["current_price"])

    return True, f"submitted rotation sell for {sell_symbol}", {
        "candidate_score": score,
        "candidate_score_reason": score_reason,
        "weakest": weakest,
        "sell_order": order_result,
    }
