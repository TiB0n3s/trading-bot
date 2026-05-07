import os
import time
import logging
import alpaca_trade_api as tradeapi

logger = logging.getLogger(__name__)

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

def get_account():
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

def get_position(symbol):
    try:
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

def place_order(symbol, action, position_size_pct, stop_loss_pct, take_profit_pct, risk_level=None):
    try:
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
                qty = int(float(existing.qty))
            except Exception as e:
                logger.error(f"Failed to fetch position for {symbol}: {e}")
                return None
            if qty <= 0:
                logger.error(f"Refusing sell for {symbol}: position qty={qty} is {'short' if qty < 0 else 'zero'}, not a long to close")
                return None
            logger.info(f"Sell order - closing full position of {qty} shares of {symbol} at {current_price} | balance: {balance}")
            try:
                open_orders = api.list_orders(status="open", symbols=[symbol])
                for o in open_orders:
                    api.cancel_order(o.id)
                    logger.info(f"Cancelled open order {o.id} ({o.side} {o.qty} {symbol} type={o.order_type}) before sell")
                time.sleep(1)
                refreshed = api.get_position(symbol)
                available_qty = int(float(refreshed.qty))
                if available_qty != qty:
                    logger.error(f"Qty mismatch after cancel for {symbol}: held={qty} available={available_qty} - aborting sell")
                    return None
                logger.info(f"Position confirmed after cancel: {symbol} qty={available_qty} available")
            except Exception as e:
                logger.error(f"Failed to cancel open orders for {symbol}: {e}")
                return None
        else:
            risk_amount = balance * (position_size_pct / 100)
            qty = int(risk_amount / current_price)
            if risk_level == "very_high" and qty >= 2:
                original_qty = qty
                qty = qty // 2
                logger.info(f"Risk multiplier applied to {symbol}: very_high risk_level — sizing halved {original_qty} → {qty}")
            logger.info(f"Buy sizing: {symbol} qty={qty} at {current_price} | risk_amount={risk_amount:.2f} balance={balance}")
            if qty < 1:
                logger.error(f"Position size too small for {symbol} - qty rounds to 0 at price {current_price} with balance {balance}")
                return None
        if side == "buy":
            stop_price = round(current_price * (1 - stop_loss_pct / 100), 2)
            take_price = round(current_price * (1 + take_profit_pct / 100), 2)
        else:
            stop_price = round(current_price * (1 + stop_loss_pct / 100), 2)
            take_price = round(current_price * (1 - take_profit_pct / 100), 2)
            logger.info(f"SELL order - Stop: {stop_price} (above entry), Target: {take_price} (below entry)")
        if side == "buy":
            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type="market",
                time_in_force="day",
                order_class="bracket",
                stop_loss={"stop_price": stop_price},
                take_profit={"limit_price": take_price}
            )
        else:
            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type="market",
                time_in_force="day"
            )
        logger.info(f"Order placed: {side.upper()} {qty} shares of {symbol} | Stop: {stop_price} | Target: {take_price}")
        return {
            "order_id": order.id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "stop_loss": stop_price,
            "take_profit": take_price,
            "status": order.status
        }
    except Exception as e:
        logger.error(f"Order placement failed: {e}")
        return None
