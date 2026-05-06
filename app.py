import os
import json
import sqlite3
import logging
import threading
from datetime import datetime, timezone, timedelta
import pytz
from pathlib import Path
from flask import Flask, request, jsonify, abort
from decision_engine import evaluate_signal, get_mock_account_state
from broker import place_order, get_account, get_position, api

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "trades.db"
_START_TIME = datetime.now(timezone.utc)

def _init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp         TEXT NOT NULL,
            symbol            TEXT,
            action            TEXT,
            signal_price      REAL,
            approved          INTEGER,
            rejection_reason  TEXT,
            confidence        TEXT,
            position_size_pct REAL,
            stop_loss_pct     REAL,
            take_profit_pct   REAL,
            order_id          TEXT,
            order_status      TEXT,
            qty               INTEGER,
            fill_price        REAL
        )
    """)
    con.commit()
    con.close()

_init_db()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def _startup_reconcile():
    try:
        # 1. Check required env vars
        for key in ("ANTHROPIC_API_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
            if not os.environ.get(key):
                logger.error(f"Startup: missing required environment variable {key}")

        # 2. Fetch Alpaca positions
        try:
            alpaca_positions = api.list_positions()
            alpaca_symbols = {p.symbol for p in alpaca_positions}
        except Exception as e:
            logger.error(f"Startup reconciliation: failed to fetch Alpaca positions: {e}")
            alpaca_symbols = set()
            alpaca_positions = []

        # 3. Query DB for symbols with a net open position (more filled buys than sells)
        db_symbols = set()
        try:
            con = sqlite3.connect(DB_PATH)
            rows = con.execute("""
                SELECT symbol,
                    SUM(CASE WHEN action = 'buy' THEN COALESCE(qty, 0)
                             ELSE -COALESCE(qty, 0) END) AS net_qty
                FROM trades
                WHERE order_id IS NOT NULL
                  AND order_status IN ('filled', 'partially_filled')
                GROUP BY symbol
                HAVING net_qty > 0
            """).fetchall()
            con.close()
            db_symbols = {row[0] for row in rows if row[0]}
        except Exception as e:
            logger.error(f"Startup reconciliation: failed to query trades.db: {e}")

        # 4. Compare and log discrepancies
        in_alpaca_not_db = alpaca_symbols - db_symbols
        in_db_not_alpaca = db_symbols - alpaca_symbols
        for sym in sorted(in_alpaca_not_db):
            logger.warning(f"Startup reconciliation: {sym} held in Alpaca but no open position tracked in trades.db")
        for sym in sorted(in_db_not_alpaca):
            logger.warning(f"Startup reconciliation: {sym} tracked as open in trades.db but not found in Alpaca positions")

        # 5. Summary
        discrepancies = len(in_alpaca_not_db) + len(in_db_not_alpaca)
        logger.info(
            f"Startup reconciliation: {len(alpaca_symbols)} positions in Alpaca, "
            f"{len(db_symbols)} tracked in DB, {discrepancies} discrepancies"
        )
    except Exception as e:
        logger.error(f"Startup reconciliation failed unexpectedly: {e}")

_startup_reconcile()

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "changeme")

APPROVED_SYMBOLS = {"AAPL", "SPY", "QQQ", "MSFT", "NVDA", "ORCL", "TSCO", "TSLA", "META", "AMD", "CVX", "XOM", "GOOGL"}

# (min, max) expected price ranges; signals outside ±20% of this range are rejected
PRICE_RANGES = {
    "AAPL": (150,  500),
    "SPY":  (400,  700),
    "QQQ":  (400,  900),
    "MSFT": (200,  600),
    "NVDA": ( 80,  600),
    "ORCL": ( 80,  300),
    "TSCO": ( 20,  80),
    "TSLA": (100,  800),
    "META": (200, 1000),
    "AMD":  ( 50,  600),
    "CVX":  (100,  260),
    "XOM":  ( 80,  215),
    "GOOGL": (250, 550),
}

_last_order: dict = {}     # {(symbol, action): datetime in ET} — reset on restart
_trend_table: dict = {}    # {symbol: {direction, strength, consecutive_count, last_signal, last_time}}
_signal_history: dict = {} # {symbol: [action, ...]} most recent first, max 10 — internal

def _compute_trend(recent_actions: list) -> dict:
    if not recent_actions:
        return {"direction": "neutral", "strength": "weak", "consecutive_count": 0, "last_signal": None}
    first = recent_actions[0]
    count = 0
    for a in recent_actions:
        if a == first:
            count += 1
        else:
            break
    direction = ("bullish" if first == "buy" else "bearish") if count >= 3 else "neutral"
    strength = "confirmed" if count >= 5 else "developing" if count >= 3 else "weak"
    return {"direction": direction, "strength": strength, "consecutive_count": count, "last_signal": first}

def _build_trend_table():
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute("""
            SELECT symbol, action, timestamp FROM (
                SELECT symbol, action, timestamp,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp DESC) AS rn
                FROM trades
                WHERE symbol IS NOT NULL AND action IS NOT NULL
            ) WHERE rn <= 10
            ORDER BY symbol, timestamp DESC
        """).fetchall()
        con.close()
        history = {}
        last_time = {}
        for sym, act, ts in rows:
            history.setdefault(sym, []).append(act)
            last_time.setdefault(sym, ts)
        for sym, actions in history.items():
            _signal_history[sym] = actions
            entry = _compute_trend(actions)
            entry["last_time"] = last_time[sym]
            _trend_table[sym] = entry
        logger.info(f"Trend table built for {len(_trend_table)} symbols")
    except Exception as e:
        logger.error(f"_build_trend_table failed: {e}")

_build_trend_table()

def validate_secret(req):
    secret = req.args.get("secret", "")
    if secret != WEBHOOK_SECRET:
        logger.warning(f"Invalid secret from {req.remote_addr}")
        abort(401)

def log_trade(signal, decision, order):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("signals.log", "a") as f:
        f.write(f"{timestamp} | SIGNAL: {json.dumps(signal)} | DECISION: {json.dumps(decision)} | ORDER: {json.dumps(order)}\n")
    try:
        approved = decision.get("approved", False)
        order = order or {}
        con = sqlite3.connect(DB_PATH)
        con.execute("""
            INSERT INTO trades (
                timestamp, symbol, action, signal_price, approved, rejection_reason,
                confidence, position_size_pct, stop_loss_pct, take_profit_pct,
                order_id, order_status, qty, fill_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            signal.get("symbol"),
            signal.get("action"),
            signal.get("price"),
            1 if approved else 0,
            None if approved else decision.get("reason"),
            decision.get("confidence"),
            decision.get("position_size_pct"),
            decision.get("stop_loss_pct"),
            decision.get("take_profit_pct"),
            order.get("order_id"),
            order.get("status"),
            order.get("qty"),
            order.get("fill_price"),
        ))
        con.commit()
        con.close()
    except Exception as e:
        logger.error(f"DB write failed for {signal.get('symbol')}: {e}")

def process_signal(data):
    action = data.get("action", "").lower()
    symbol = data.get("symbol", "")
    price = data.get("price", 0)
    logger.info(f"Processing {action.upper()} signal for {symbol} at {price}")
    account_state = get_mock_account_state()

    # Update trend table with this incoming signal before any pre-checks
    _now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _signal_history.setdefault(symbol, []).insert(0, action)
    _signal_history[symbol] = _signal_history[symbol][:10]
    _trend_table[symbol] = {**_compute_trend(_signal_history[symbol]), "last_time": _now_ts}

    # Hard pre-check 1: market hours (9:45–15:45 ET, weekdays only)
    now_et = datetime.now(pytz.timezone("America/New_York"))
    if now_et.weekday() >= 5:
        logger.warning(f"Market hours check failed for {symbol} {action.upper()}: weekend ({now_et.strftime('%A')})")
        return
    t = now_et.hour * 60 + now_et.minute
    if not (9 * 60 + 45 <= t < 15 * 60 + 45):
        logger.warning(f"Market hours check failed for {symbol} {action.upper()}: {now_et.strftime('%H:%M')} ET is outside 09:45–15:45 window")
        return

    # Hard pre-check 2: circuit breaker (-3% daily loss limit)
    daily_pnl_pct = account_state.get("daily_pnl_pct", 0.0)
    if daily_pnl_pct < -3.0:
        logger.error(f"Circuit breaker triggered for {symbol} {action.upper()}: daily P&L is {daily_pnl_pct:.2f}% (limit: -3.0%)")
        return

    if action == "sell":
        try:
            api.get_position(symbol)
        except Exception:
            logger.warning(f"Skipping SELL signal for {symbol} — no open position in Alpaca")
            return
    existing_position = get_position(symbol)
    if existing_position:
        account_state["current_symbol_position"] = existing_position

    # Cooldown check: skip if same symbol+action had a successful order within 15 min
    cooldown_key = (symbol, action)
    last = _last_order.get(cooldown_key)
    if last and (now_et - last).total_seconds() < 15 * 60:
        mins_remaining = int(15 * 60 - (now_et - last).total_seconds()) // 60
        logger.warning(
            f"Cooldown active for {symbol} {action.upper()}: last order at {last.strftime('%H:%M')} ET, "
            f"{mins_remaining}m remaining — skipping Claude"
        )
        return

    # Hard pre-check: 4% per-symbol exposure cap (buy signals only)
    if action == "buy" and existing_position:
        balance = account_state.get("balance", 0)
        position_value = existing_position["qty"] * existing_position["current_price"]
        if balance > 0:
            exposure_pct = position_value / balance * 100
            if exposure_pct >= 4.0:
                logger.warning(
                    f"Exposure cap reached for {symbol} BUY: "
                    f"current position ${position_value:.2f} = {exposure_pct:.2f}% of balance "
                    f"(limit: 4.0%) — skipping Claude"
                )
                return

    account_state["trend_table"] = _trend_table
    decision = evaluate_signal(data, account_state)
    order_result = None

    # Confidence gate: reject low-confidence buy signals without placing an order
    if action == "buy" and decision.get("confidence") == "low":
        logger.warning(f"Low confidence BUY rejected for {symbol}: skipping order placement")
        log_trade(data, decision, None)
        return

    if decision.get("approved"):
        approved_reason = decision.get("reason")
        logger.info(f"APPROVED: {symbol} {action.upper()} - {approved_reason}")
        order_result = place_order(
            symbol=symbol,
            action=action,
            position_size_pct=decision.get("position_size_pct", 1.0),
            stop_loss_pct=decision.get("stop_loss_pct", 0.5),
            take_profit_pct=decision.get("take_profit_pct", 1.5)
        )
        if order_result:
            logger.info(f"ORDER PLACED: {order_result}")
            _last_order[cooldown_key] = now_et
        else:
            logger.error(f"Order placement failed for {symbol}")
    else:
        rejected_reason = decision.get("reason")
        logger.info(f"REJECTED: {symbol} {action.upper()} - {rejected_reason}")
    log_trade(data, decision, order_result)

@app.route("/webhook", methods=["POST"])
def webhook():
    validate_secret(request)
    if not request.is_json:
        logger.warning("Non-JSON payload received")
        abort(400)
    data = request.get_json()
    if data is None:
        logger.warning("Empty or unparseable JSON payload")
        abort(400)
    logger.info(f"Signal received: {data}")
    action = data.get("action", "").lower()
    symbol = data.get("symbol", "").upper()
    price = data.get("price", 0)
    if not action or not symbol:
        logger.warning("Missing action or symbol")
        abort(400)
    if action not in ["buy", "sell"]:
        logger.warning(f"Unknown action: {action}")
        abort(400)
    if symbol not in APPROVED_SYMBOLS:
        logger.warning(f"Rejected unapproved symbol: {symbol}")
        abort(400)
    try:
        price = float(price)
    except (TypeError, ValueError):
        logger.warning(f"Non-numeric price rejected: {price!r}")
        abort(400)
    if price <= 0:
        logger.warning(f"Non-positive price rejected for {symbol}: {price}")
        abort(400)
    low, high = PRICE_RANGES[symbol]
    if not (low * 0.8 <= price <= high * 1.2):
        logger.warning(f"Price sanity check failed for {symbol}: {price} outside [{low * 0.8:.2f}, {high * 1.2:.2f}]")
        abort(400)
    thread = threading.Thread(target=process_signal, args=(data,))
    thread.daemon = True
    thread.start()
    return jsonify({"status": "received", "symbol": symbol, "action": action, "price": price, "timestamp": datetime.now().isoformat()}), 200

@app.route("/health", methods=["GET"])
def health():
    account = get_account()
    return jsonify({
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "account": account
    }), 200

def _market_session():
    ET = timezone(timedelta(hours=-4))  # EDT (UTC-4), adjust to -5 in winter
    now = datetime.now(ET)
    t = now.hour * 60 + now.minute
    if t < 9 * 60 + 30:
        return "pre-market"
    if t < 16 * 60:
        return "open"
    if t < 20 * 60:
        return "after-hours"
    return "closed"


@app.route("/status", methods=["GET"])
def status():
    result = {"timestamp": datetime.now().isoformat()}

    # Uptime
    try:
        elapsed = datetime.now(timezone.utc) - _START_TIME
        h, rem = divmod(int(elapsed.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        result["uptime"] = f"{h}h {m}m {s}s"
    except Exception:
        pass

    # Market session
    try:
        result["market_session"] = _market_session()
    except Exception:
        pass

    # Account summary + daily P&L (via get_mock_account_state)
    try:
        state = get_mock_account_state()
        balance = state.get("balance", 0)
        result["account"] = {
            "balance":         balance,
            "portfolio_value": state.get("portfolio_value"),
            "daily_pnl":       state.get("daily_pnl"),
            "daily_pnl_pct":   state.get("daily_pnl_pct"),
            "circuit_breaker_triggered": (state.get("daily_pnl_pct") or 0) <= -3.0,
        }
    except Exception as e:
        logger.error(f"/status account error: {e}")
        balance = 0

    # Buying power (get_account has it; get_mock_account_state does not)
    try:
        acct = get_account()
        if acct and "account" in result:
            result["account"]["buying_power"] = acct["buying_power"]
    except Exception:
        pass

    # Detailed positions
    try:
        positions = api.list_positions()
        result["positions"] = [
            {
                "symbol":       p.symbol,
                "qty":          float(p.qty),
                "current_price": float(p.current_price),
                "value":        float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "pct_of_balance": round(float(p.market_value) / balance * 100, 2) if balance else None,
            }
            for p in sorted(positions, key=lambda x: -float(x.market_value))
        ]
        result["position_count"] = f"{len(positions)}/8"
    except Exception as e:
        logger.error(f"/status positions error: {e}")

    # Today's signal counts from trades.db
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        con = sqlite3.connect(DB_PATH)
        counts = con.execute("""
            SELECT
                COUNT(*)                                          AS total,
                SUM(approved)                                     AS approved,
                SUM(1 - approved)                                 AS rejected,
                SUM(CASE WHEN order_id IS NOT NULL THEN 1 END)    AS orders_placed,
                SUM(CASE WHEN approved=1 AND order_id IS NULL
                         THEN 1 END)                              AS null_orders
            FROM trades WHERE timestamp LIKE ?
        """, (f"{today}%",)).fetchone()
        con.close()
        result["today_signals"] = {
            "total":         counts[0],
            "approved":      counts[1] or 0,
            "rejected":      counts[2] or 0,
            "orders_placed": counts[3] or 0,
            "null_orders":   counts[4] or 0,
        }
    except Exception as e:
        logger.error(f"/status signal counts error: {e}")

    return jsonify(result), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
