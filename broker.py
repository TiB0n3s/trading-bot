import os
import time
import logging
from typing import Any
import alpaca_trade_api as tradeapi
from exceptions import BrokerError, ValidationError
from runtime_config import (
    EXECUTION_MODE,
    LIVE_TRADING_ENABLED,
    get_alpaca_base_url,
    is_cash_mode,
    max_order_dollars,
)
from execution.order_policy import (
    calculate_buy_qty,
    calculate_bracket_prices,
    cash_order_cap_check,
)

logger = logging.getLogger(__name__)

EXECUTION_POLICY_MODE = os.getenv("EXECUTION_POLICY_MODE", "compare").strip().lower()
if EXECUTION_POLICY_MODE not in ("off", "compare"):
    logger.warning(
        f"Invalid EXECUTION_POLICY_MODE={EXECUTION_POLICY_MODE!r}; defaulting to compare"
    )
    EXECUTION_POLICY_MODE = "compare"

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = get_alpaca_base_url()
SELL_CANCEL_POLL_ATTEMPTS = int(os.getenv("SELL_CANCEL_POLL_ATTEMPTS", "5"))
SELL_CANCEL_POLL_SLEEP_SECONDS = float(os.getenv("SELL_CANCEL_POLL_SLEEP_SECONDS", "0.5"))

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        raise ValidationError("symbol is required")
    if not normalized.replace(".", "").replace("-", "").isalnum():
        raise ValidationError(f"invalid symbol={symbol!r}")
    return normalized


def _normalize_action(action: str) -> str:
    normalized = str(action or "").strip().lower()
    if normalized not in ("buy", "sell"):
        raise ValidationError(f"invalid action={action!r}; expected buy or sell")
    return normalized


def _positive_float(name: str, value: Any, *, allow_zero: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be numeric") from exc

    if allow_zero:
        if parsed < 0:
            raise ValidationError(f"{name} must be >= 0")
    elif parsed <= 0:
        raise ValidationError(f"{name} must be > 0")
    return parsed


def _optional_positive_int(name: str, value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValidationError(f"{name} must be > 0")
    return parsed


def validate_order_request(
    symbol: str,
    action: str,
    position_size_pct: Any,
    stop_loss_pct: Any,
    take_profit_pct: Any,
    qty_override: Any = None,
) -> dict[str, Any]:
    """Validate and normalize broker order inputs without calling Alpaca."""
    normalized_action = _normalize_action(action)
    return {
        "symbol": _normalize_symbol(symbol),
        "action": normalized_action,
        "position_size_pct": _positive_float(
            "position_size_pct",
            position_size_pct,
            allow_zero=normalized_action == "sell",
        ),
        "stop_loss_pct": _positive_float("stop_loss_pct", stop_loss_pct, allow_zero=True),
        "take_profit_pct": _positive_float("take_profit_pct", take_profit_pct, allow_zero=True),
        "qty_override": _optional_positive_int("qty_override", qty_override),
    }


def _classify_broker_exception(exc: Exception) -> BrokerError:
    """Wrap broker exceptions with a structured type while preserving context."""
    wrapped = BrokerError(str(exc))
    wrapped.__cause__ = exc
    return wrapped


def _wait_for_open_order_cancels(symbol: str) -> list[Any]:
    """Poll open orders until cancel requests have settled or attempts expire."""
    remaining: list[Any] = []
    for attempt in range(1, SELL_CANCEL_POLL_ATTEMPTS + 1):
        remaining = list(api.list_orders(status="open", symbols=[symbol]) or [])
        if not remaining:
            return []
        logger.info(
            f"Waiting for {len(remaining)} open order cancel(s) for {symbol} "
            f"attempt={attempt}/{SELL_CANCEL_POLL_ATTEMPTS}"
        )
        time.sleep(SELL_CANCEL_POLL_SLEEP_SECONDS)
    return remaining


def get_account() -> dict[str, Any] | None:
    try:
        account = api.get_account()
        return {
            "balance": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "buying_power": float(account.buying_power),
            "status": account.status
        }
    except Exception as e:
        logger.error(f"Failed to get account: {e}")
        return None


def get_position(symbol: str) -> dict[str, Any] | None:
    try:
        symbol = _normalize_symbol(symbol)
        position = api.get_position(symbol)
        return {
            "symbol": symbol,
            "qty": float(position.qty),
            "avg_entry": float(position.avg_entry_price),
            "current_price": float(position.current_price),
            "unrealized_pl": float(position.unrealized_pl)
        }
    except Exception as e:
        logger.info(f"No position found for {symbol}: {e}")
        return None


def place_order(
    symbol: str,
    action: str,
    position_size_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    risk_level: str | None = None,
    client_order_id: str | None = None,
    qty_override: int | None = None,
) -> dict[str, Any] | None:
    try:
        request = validate_order_request(
            symbol=symbol,
            action=action,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            qty_override=qty_override,
        )
        symbol = request["symbol"]
        action = request["action"]
        position_size_pct = request["position_size_pct"]
        stop_loss_pct = request["stop_loss_pct"]
        take_profit_pct = request["take_profit_pct"]
        qty_override = request["qty_override"]

        if is_cash_mode() and not LIVE_TRADING_ENABLED:
            logger.error(
                f"LIVE GUARD: refusing {action.upper()} {symbol} because "
                f"EXECUTION_MODE={EXECUTION_MODE} but LIVE_TRADING_ENABLED is false"
            )
            return None        
        account = get_account()
        if not account:
            logger.error("Cannot place order - account unavailable")
            return None
        balance = account["balance"]
        quote = api.get_latest_trade(symbol)
        current_price = float(quote.price)
        side = "buy" if action == "buy" else "sell"
        if side == "sell":
            try:
                existing = api.get_position(symbol)
                position_qty = int(float(existing.qty))

                if qty_override is not None:
                    qty = min(int(qty_override), position_qty)
                else:
                    qty = position_qty

            except Exception as e:
                logger.error(f"Failed to fetch position for {symbol}: {_classify_broker_exception(e)}", exc_info=True)
                return None

            if qty <= 0:
                logger.error(f"Refusing sell for {symbol}: position qty={qty} is {'short' if qty < 0 else 'zero'}, not a long to close")
                return None

            if qty < position_qty:
                logger.info(
                    f"Sell order - closing partial position of {qty}/{position_qty} shares of {symbol} "
                    f"at {current_price} | balance: {balance}"
                )
            else:
                logger.info(
                    f"Sell order - closing full position of {qty} shares of {symbol} "
                    f"at {current_price} | balance: {balance}"
                )
            try:
                open_orders = api.list_orders(status="open", symbols=[symbol])
                for o in open_orders:
                    api.cancel_order(o.id)
                    logger.info(f"Cancelled open order {o.id} ({o.side} {o.qty} {symbol} type={o.order_type}) before sell")

                remaining_orders = _wait_for_open_order_cancels(symbol)
                if remaining_orders:
                    logger.error(
                        f"Open orders still present after cancel polling for {symbol}: "
                        f"{[getattr(o, 'id', '?') for o in remaining_orders]}"
                    )
                    return None
                
                refreshed = api.get_position(symbol)
                available_qty = int(float(refreshed.qty))

                if available_qty < qty:
                    logger.error(
                        f"Qty mismatch after cancel for {symbol}: requested_sell={qty} "
                        f"available={available_qty} - aborting sell"
                    )
                    return None

                logger.info(
                    f"Position confirmed after cancel: {symbol} requested_sell={qty} "
                    f"available={available_qty}"
                )
            except Exception as e:
                logger.error(f"Failed to cancel open orders for {symbol}: {_classify_broker_exception(e)}", exc_info=True)
                return None
        else:
            risk_amount = balance * (position_size_pct / 100)
            qty = int(risk_amount / current_price)
            if risk_level == "very_high" and qty >= 2:
                original_qty = qty
                qty = qty // 2
                logger.info(f"Risk multiplier applied to {symbol}: very_high risk_level — sizing halved {original_qty} → {qty}")

            if EXECUTION_POLICY_MODE == "compare":
                try:
                    policy_qty = calculate_buy_qty(
                        balance=balance,
                        position_size_pct=position_size_pct,
                        current_price=current_price,
                        risk_level=risk_level,
                    )
                    logger.info(
                        f"EXECUTION_POLICY_COMPARE qty {symbol}: "
                        f"live_qty={qty} "
                        f"policy_qty={policy_qty.get('qty')} "
                        f"allowed={policy_qty.get('allowed')} "
                        f"risk_amount_live={risk_amount:.2f} "
                        f"risk_amount_policy={policy_qty.get('risk_amount')} "
                        f"reason={policy_qty.get('reason')} "
                        f"risk_adjustment={policy_qty.get('risk_adjustment')}"
                    )
                except Exception as e:
                    logger.warning(f"EXECUTION_POLICY_COMPARE qty failed for {symbol}: {e}")

            logger.info(f"Buy sizing: {symbol} qty={qty} at {current_price} | risk_amount={risk_amount:.2f} balance={balance}")
            if qty < 1:
                logger.error(f"Position size too small for {symbol} - qty rounds to 0 at price {current_price} with balance {balance}")
                return None
            if is_cash_mode():
                order_notional = qty * current_price
                cap = max_order_dollars()

                if EXECUTION_POLICY_MODE == "compare":
                    try:
                        policy_cap = cash_order_cap_check(
                            qty=qty,
                            current_price=current_price,
                            max_order_dollars=cap,
                        )
                        logger.info(
                            f"EXECUTION_POLICY_COMPARE cash_cap {symbol}: "
                            f"live_notional={order_notional:.2f} "
                            f"policy_notional={policy_cap.get('notional')} "
                            f"cap={policy_cap.get('max_order_dollars')} "
                            f"allowed={policy_cap.get('allowed')} "
                            f"reason={policy_cap.get('reason')}"
                        )
                    except Exception as e:
                        logger.warning(f"EXECUTION_POLICY_COMPARE cash_cap failed for {symbol}: {e}")

                if order_notional > cap:
                    logger.error(
                        f"LIVE GUARD: refusing BUY {symbol}; notional ${order_notional:.2f} "
                        f"exceeds max_order_dollars ${cap:.2f} "
                        f"(EXECUTION_MODE={EXECUTION_MODE})"
                    )
                    return None
        if side == "buy":
            stop_price = round(current_price * (1 - stop_loss_pct / 100), 2)
            take_price = round(current_price * (1 + take_profit_pct / 100), 2)
        else:
            stop_price = round(current_price * (1 + stop_loss_pct / 100), 2)
            take_price = round(current_price * (1 - take_profit_pct / 100), 2)
            logger.info(f"SELL order - Stop: {stop_price} (above entry), Target: {take_price} (below entry)")

        if EXECUTION_POLICY_MODE == "compare":
            try:
                policy_bracket = calculate_bracket_prices(
                    side=side,
                    current_price=current_price,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                )
                logger.info(
                    f"EXECUTION_POLICY_COMPARE bracket {symbol}: "
                    f"side={side} "
                    f"live_stop={stop_price} "
                    f"policy_stop={policy_bracket.get('stop_price')} "
                    f"live_take={take_price} "
                    f"policy_take={policy_bracket.get('take_profit_price')} "
                    f"allowed={policy_bracket.get('allowed')} "
                    f"reason={policy_bracket.get('reason')}"
                )
            except Exception as e:
                logger.warning(f"EXECUTION_POLICY_COMPARE bracket failed for {symbol}: {e}")
        if side == "buy":
            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type="market",
                time_in_force="day",
                order_class="bracket",
                stop_loss={"stop_price": stop_price},
                take_profit={"limit_price": take_price},
                client_order_id=client_order_id,
            )
        else:
            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type="market",
                time_in_force="day",
                client_order_id=client_order_id,
            )
        logger.info(f"Order placed: {side.upper()} {qty} shares of {symbol} | Stop: {stop_price} | Target: {take_price}")
        return {
            "order_id": order.id,
            "client_order_id": getattr(order, "client_order_id", client_order_id),
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "stop_loss": stop_price,
            "take_profit": take_price,
            "status": order.status
        }
    except ValidationError as e:
        logger.error(f"Invalid order request: {e}")
        return None
    except Exception as e:
        logger.error(f"Order placement failed: {e}")
        return None
