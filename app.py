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
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
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

APPROVED_SYMBOLS = {"AAPL", "SPY", "QQQ", "MSFT", "NVDA", "ORCL", "TSCO", "TSLA", "META", "AMD", "CVX", "XOM", "GOOGL", "GLD", "IWM"}

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
    "GLD":   (250, 550),
    "IWM":   (180, 350),
}

_last_order: dict = {}     # {(symbol, action): datetime in ET} — reset on restart
_last_sell: dict = {}      # {symbol: (datetime in ET, price)} — last successful sell, for churn prevention
_trend_table: dict = {}    # {symbol: {direction, strength, consecutive_count, last_signal, last_time}}
_signal_history: dict = {} # {symbol: [action, ...]} most recent first, max 10 — internal
_market_bias: dict = {}    # {symbol: {bias, reason, confidence}} — populated from market_context.json
_market_context_mtime: float = 0  # last seen mtime of market_context.json, used for lazy refresh

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

def _load_market_context():
    """Load same-day pre-market research into _market_bias.
    Lazy-refreshes when market_context.json mtime changes so the bot picks up
    each day's cron output without a service restart."""
    global _market_context_mtime
    path = Path(__file__).parent / "market_context.json"
    if not path.exists():
        return
    try:
        current_mtime = path.stat().st_mtime
        if current_mtime <= _market_context_mtime:
            return
        _market_context_mtime = current_mtime
        ctx = json.loads(path.read_text())
        market_date = ctx.get("market_date")
        today = datetime.now(pytz.timezone("America/New_York")).date().isoformat()
        _market_bias.clear()
        if market_date != today:
            logger.warning(f"market_context.json is stale (market_date={market_date}, today={today}) — cleared market bias")
            return
        symbols = ctx.get("symbols") or {}
        for sym, entry in symbols.items():
            if isinstance(entry, dict) and entry.get("bias") in ("buy", "avoid", "neutral"):
                _market_bias[sym] = {
                    "bias": entry["bias"],
                    "reason": entry.get("reason", ""),
                    "confidence": entry.get("confidence", ""),
                    "risk_level": entry.get("risk_level"),
                    "entry_quality": entry.get("entry_quality"),
                }
        avoid_count = sum(1 for v in _market_bias.values() if v["bias"] == "avoid")
        buy_count = sum(1 for v in _market_bias.values() if v["bias"] == "buy")
        neutral_count = sum(1 for v in _market_bias.values() if v["bias"] == "neutral")
        macro = ctx.get("macro_sentiment", "unknown")
        logger.info(
            f"Market bias loaded for {len(_market_bias)} symbols "
            f"(buy={buy_count}, avoid={avoid_count}, neutral={neutral_count}, macro={macro})"
        )
    except Exception as e:
        logger.error(f"_load_market_context failed: {e}")

_load_market_context()

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

def log_rejection(symbol, action, category, reason, price=None):
    """Persist a pre-Claude rejection to trades.db so daily_summary can count it.

    Caller is responsible for the human-readable logger.warning line; this helper
    only writes the DB row. The rejection_reason column stores '<category>: <reason>'
    so daily_summary.py can group by category prefix without parsing free-form text.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_reason = f"{category}: {reason}"
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "INSERT INTO trades (timestamp, symbol, action, signal_price, approved, rejection_reason) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (timestamp, symbol, action, price, full_reason),
        )
        con.commit()
        con.close()
    except Exception as e:
        logger.error(f"log_rejection DB write failed for {symbol}: {e}")

def get_momentum(symbol, price):
    try:
        start = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        bars = list(api.get_bars(symbol, '1Min', start=start, feed='iex'))
        if len(bars) < 2:
            return None
        bars = bars[-5:]
        first_close = float(bars[0].c)
        last_close = float(bars[-1].c)
        if first_close <= 0 or last_close <= 0:
            return None
        momentum_pct = (last_close - first_close) / first_close * 100
        price_vs_bars = (price - last_close) / last_close * 100 if last_close > 0 else 0.0
        if momentum_pct > 0.1:
            direction = "rising"
        elif momentum_pct < -0.1:
            direction = "falling"
        else:
            direction = "flat"
        return {
            "direction": direction,
            "momentum_pct": round(momentum_pct, 3),
            "price_vs_bars": round(price_vs_bars, 3),
            "bar_count": len(bars),
            "last_close": round(last_close, 4),
        }
    except Exception as e:
        logger.warning(f"get_momentum failed for {symbol}: {e}")
        return None

def process_signal(data):
    _load_market_context()  # lazy refresh — reloads when market_context.json mtime changes
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
        log_rejection(symbol, action, "market_hours", f"weekend ({now_et.strftime('%A')})", price=price)
        return
    t = now_et.hour * 60 + now_et.minute
    if not (9 * 60 + 45 <= t < 15 * 60 + 45):
        logger.warning(f"Market hours check failed for {symbol} {action.upper()}: {now_et.strftime('%H:%M')} ET is outside 09:45–15:45 window")
        log_rejection(symbol, action, "market_hours", f"{now_et.strftime('%H:%M')} ET outside 09:45–15:45 window", price=price)
        return

    # Hard pre-check 2: circuit breaker (-3% daily loss limit)
    daily_pnl_pct = account_state.get("daily_pnl_pct", 0.0)
    if daily_pnl_pct < -3.0:
        logger.error(f"Circuit breaker triggered for {symbol} {action.upper()}: daily P&L is {daily_pnl_pct:.2f}% (limit: -3.0%)")
        log_rejection(symbol, action, "circuit_breaker", f"daily P&L {daily_pnl_pct:.2f}% < -3.0%", price=price)
        return

    if action == "sell":
        try:
            api.get_position(symbol)
        except Exception:
            logger.warning(f"Skipping SELL signal for {symbol} — no open position in Alpaca")
            log_rejection(symbol, action, "ghost_sell", "no open Alpaca position", price=price)
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
        log_rejection(symbol, action, "cooldown", f"{mins_remaining}m remaining (last order {last.strftime('%H:%M')} ET)", price=price)
        return

    # Sell→buy churn prevention: block buys that follow a recent sell on the same symbol
    if action == "buy":
        last_sell = _last_sell.get(symbol)
        if last_sell:
            last_sell_time, last_sell_price = last_sell
            elapsed_s = (now_et - last_sell_time).total_seconds()
            if elapsed_s < 30 * 60:
                mins_remaining = int(30 * 60 - elapsed_s) // 60
                logger.warning(
                    f"Sell→buy churn block for {symbol}: sold at {last_sell_time.strftime('%H:%M')} ET "
                    f"(${last_sell_price:.2f}), {mins_remaining}m remaining in 30-min window — skipping Claude"
                )
                log_rejection(symbol, action, "churn_window", f"sold at ${last_sell_price:.2f}, {mins_remaining}m remaining in 30-min window", price=price)
                return
            if last_sell_price > 0:
                price_diff_pct = abs(price - last_sell_price) / last_sell_price * 100
                if price_diff_pct < 0.5:
                    logger.warning(
                        f"Sell→buy churn block for {symbol}: signal price ${price:.2f} within "
                        f"{price_diff_pct:.2f}% of last sell price ${last_sell_price:.2f} — skipping Claude"
                    )
                    log_rejection(symbol, action, "churn_price", f"signal ${price:.2f} within {price_diff_pct:.2f}% of last sell ${last_sell_price:.2f}", price=price)
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
                log_rejection(symbol, action, "exposure_cap", f"position ${position_value:.2f} = {exposure_pct:.2f}% of balance (limit 4.0%)", price=price)
                return

    # Trend gate: block buy signals on symbols with established neutral/bearish trend
    # (new symbols with no prior history pass through — block only applies once history exists)
    if action == "buy":
        history = _signal_history.get(symbol, [])
        trend = _trend_table.get(symbol)
        if len(history) > 1 and trend and trend.get("direction") in ("neutral", "bearish"):
            logger.warning(
                f"Trend gate blocked {symbol} BUY: direction={trend.get('direction')} "
                f"strength={trend.get('strength')} "
                f"consecutive_count={trend.get('consecutive_count')} — skipping Claude"
            )
            log_rejection(symbol, action, "trend_gate", f"direction={trend.get('direction')} strength={trend.get('strength')} count={trend.get('consecutive_count')}", price=price)
            return

    # Market bias gate: block buy if pre-market research flagged 'avoid'; inject 'buy' bias for Claude
    if action == "buy":
        bias_entry = _market_bias.get(symbol)
        if bias_entry:
            bias = bias_entry["bias"]
            if bias == "avoid":
                logger.warning(
                    f"Market bias gate blocked {symbol} BUY: pre-market research flagged 'avoid' "
                    f"(confidence={bias_entry.get('confidence','')}) — reason: {bias_entry.get('reason','')}"
                )
                log_rejection(symbol, action, "market_bias_avoid", f"confidence={bias_entry.get('confidence','')} reason={bias_entry.get('reason','')}", price=price)
                return
            if bias == "buy":
                account_state["market_bias"] = "buy"
            # Pass quality fields through to Claude regardless of bias direction
            if bias_entry.get("risk_level"):
                account_state["risk_level"] = bias_entry["risk_level"]
            if bias_entry.get("entry_quality"):
                account_state["entry_quality"] = bias_entry["entry_quality"]

    # Chase prevention gate: hard reject buy signals flagged 'do_not_chase' or 'avoid_chasing'
    # in the pre-market brief — typically extended/parabolic names where fundamentals are
    # strong but the entry is tactically poor (e.g. AMD post-earnings gap, NVDA after a run).
    if action == "buy":
        bias_entry = _market_bias.get(symbol)
        if bias_entry:
            eq = bias_entry.get("entry_quality")
            if eq in ("do_not_chase", "avoid_chasing"):
                logger.warning(
                    f"Chase prevention gate blocked {symbol} BUY: entry_quality={eq}, "
                    f"risk_level={bias_entry.get('risk_level') or '-'} — skipping Claude"
                )
                log_rejection(symbol, action, "chase_prevention", f"entry_quality={eq} risk_level={bias_entry.get('risk_level') or '-'}", price=price)
                return

    # Momentum check (buy signals only, fail-open — never blocks trading)
    if action == "buy":
        momentum = get_momentum(symbol, price)
        if momentum:
            account_state["momentum"] = momentum
            if momentum["direction"] == "falling" and momentum["momentum_pct"] < -0.15:
                account_state["signal_confidence_hint"] = "low"
                logger.warning(
                    f"Momentum caution for {symbol} BUY: direction={momentum['direction']} "
                    f"momentum_pct={momentum['momentum_pct']}% last_close={momentum['last_close']} "
                    f"— downgrading confidence hint to low"
                )
            elif momentum["direction"] == "rising":
                account_state["signal_confidence_hint"] = "high"
                logger.info(
                    f"Momentum confirms {symbol} BUY: direction={momentum['direction']} "
                    f"momentum_pct={momentum['momentum_pct']}% — confidence hint set to high"
                )

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
            take_profit_pct=decision.get("take_profit_pct", 1.5),
            risk_level=account_state.get("risk_level"),
        )
        if order_result:
            logger.info(f"ORDER PLACED: {order_result}")
            _last_order[cooldown_key] = now_et
            if action == "sell":
                _last_sell[symbol] = (now_et, price)
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

    # Detailed positions (now with trend, market_bias, and exposure-cap signals)
    symbols_at_cap = []
    try:
        alpaca_positions = api.list_positions()
        pos_list = []
        for p in sorted(alpaca_positions, key=lambda x: -float(x.market_value)):
            try:
                mv = float(p.market_value)
                pct_of_balance = round(mv / balance * 100, 2) if balance else None
                cap_hit = bool(pct_of_balance is not None and pct_of_balance >= 4.0)
                if cap_hit:
                    symbols_at_cap.append(p.symbol)
                trend = _trend_table.get(p.symbol) or {}
                bias_entry = _market_bias.get(p.symbol) or {}
                pos_list.append({
                    "symbol":          p.symbol,
                    "qty":             float(p.qty),
                    "current_price":   float(p.current_price),
                    "value":           mv,
                    "unrealized_pl":   float(p.unrealized_pl),
                    "pct_of_balance":  pct_of_balance,
                    "trend_direction": trend.get("direction"),
                    "trend_strength":  trend.get("strength"),
                    "market_bias":     bias_entry.get("bias"),
                    "exposure_cap_hit": cap_hit,
                })
            except Exception as e:
                logger.warning(f"/status per-symbol error for {p.symbol}: {e}")
        result["positions"] = pos_list
        result["position_count"] = f"{len(alpaca_positions)}/8"
    except Exception as e:
        logger.error(f"/status positions error: {e}")

    # Pre-check state — what would block / pass right now if a buy signal arrived
    try:
        now_et = datetime.now(pytz.timezone("America/New_York"))
        t_min = now_et.hour * 60 + now_et.minute
        market_hours_open = (
            now_et.weekday() < 5
            and (9 * 60 + 45) <= t_min < (15 * 60 + 45)
        )

        cooldowns = []
        for (sym, action), ts in _last_order.items():
            elapsed = (now_et - ts).total_seconds()
            if elapsed < 15 * 60:
                cooldowns.append({
                    "symbol": sym,
                    "action": action,
                    "minutes_remaining": int((15 * 60 - elapsed) // 60),
                })

        churn = []
        for sym, val in _last_sell.items():
            try:
                ts = val[0] if isinstance(val, tuple) else val
                elapsed = (now_et - ts).total_seconds()
                if elapsed < 30 * 60:
                    churn.append(sym)
            except Exception:
                pass

        trend_blocked = [
            {"symbol": sym, "direction": t.get("direction"), "strength": t.get("strength")}
            for sym, t in _trend_table.items()
            if sym in APPROVED_SYMBOLS and t.get("direction") in ("neutral", "bearish")
        ]

        bias_avoid = sorted(
            sym for sym, entry in _market_bias.items()
            if (entry or {}).get("bias") == "avoid"
        )

        daily_pnl_pct = result.get("account", {}).get("daily_pnl_pct")
        result["pre_check_state"] = {
            "market_hours_open": market_hours_open,
            "circuit_breaker_active": (daily_pnl_pct or 0) < -3.0,
            "symbols_on_cooldown": sorted(cooldowns, key=lambda c: (c["symbol"], c["action"])),
            "symbols_on_churn_block": sorted(churn),
            "symbols_at_exposure_cap": sorted(symbols_at_cap),
            "trend_gate_blocked": sorted(trend_blocked, key=lambda x: x["symbol"]),
            "market_bias_avoided": bias_avoid,
        }
    except Exception as e:
        logger.error(f"/status pre_check_state error: {e}")

    # Trend snapshot for all 15 approved symbols (not just held positions)
    try:
        result["trend_table_summary"] = {
            sym: (
                {"direction": t.get("direction"), "strength": t.get("strength")}
                if (t := _trend_table.get(sym)) else None
            )
            for sym in sorted(APPROVED_SYMBOLS)
        }
    except Exception as e:
        logger.error(f"/status trend_table_summary error: {e}")

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


@app.route("/positions", methods=["GET"])
def positions():
    validate_secret(request)
    result = {"timestamp": datetime.now().isoformat()}

    balance = 0.0
    daily_pnl_pct = None
    try:
        state = get_mock_account_state()
        balance = float(state.get("balance") or 0)
        daily_pnl_pct = state.get("daily_pnl_pct")
    except Exception as e:
        logger.error(f"/positions account state error: {e}")

    def _cooldown_active(symbol):
        try:
            now_et = datetime.now(pytz.timezone("America/New_York"))
            for (sym, _action), ts in _last_order.items():
                if sym == symbol and (now_et - ts).total_seconds() < 15 * 60:
                    return True
        except Exception:
            pass
        return False

    positions_list = []
    total_unrealized = 0.0
    try:
        for p in api.list_positions():
            try:
                qty = float(p.qty)
                avg_entry = float(p.avg_entry_price)
                current = float(p.current_price)
                market_value = float(p.market_value)
                unrealized_pl = float(p.unrealized_pl)
                unrealized_pl_pct = float(p.unrealized_plpc) * 100
                exposure_pct = (market_value / balance * 100) if balance else None
                trend = _trend_table.get(p.symbol) or {}
                bias_entry = _market_bias.get(p.symbol) or {}
                positions_list.append({
                    "symbol": p.symbol,
                    "qty": qty,
                    "avg_entry_price": round(avg_entry, 4),
                    "current_price": round(current, 4),
                    "market_value": round(market_value, 2),
                    "unrealized_pl": round(unrealized_pl, 2),
                    "unrealized_pl_pct": round(unrealized_pl_pct, 3),
                    "exposure_pct": round(exposure_pct, 2) if exposure_pct is not None else None,
                    "exposure_cap_hit": bool(exposure_pct is not None and exposure_pct >= 4.0),
                    "trend_direction": trend.get("direction"),
                    "trend_strength": trend.get("strength"),
                    "market_bias": bias_entry.get("bias"),
                    "cooldown_active": _cooldown_active(p.symbol),
                })
                total_unrealized += unrealized_pl
            except Exception as e:
                logger.warning(f"/positions per-symbol error for {p.symbol}: {e}")
    except Exception as e:
        logger.error(f"/positions list_positions error: {e}")

    market_context_date = None
    macro_sentiment = None
    try:
        _load_market_context()  # opportunistic lazy refresh
        ctx_path = Path(__file__).parent / "market_context.json"
        if ctx_path.exists():
            ctx = json.loads(ctx_path.read_text())
            market_context_date = ctx.get("market_date")
            macro_sentiment = ctx.get("macro_sentiment")
    except Exception as e:
        logger.error(f"/positions market_context read error: {e}")

    result["summary"] = {
        "total_positions": len(positions_list),
        "max_positions": 8,
        "total_unrealized_pl": round(total_unrealized, 2),
        "account_balance": balance,
        "daily_pnl_pct": daily_pnl_pct,
        "market_context_date": market_context_date,
        "macro_sentiment": macro_sentiment,
    }
    result["positions"] = sorted(positions_list, key=lambda x: -(x.get("market_value") or 0))
    return jsonify(result), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
