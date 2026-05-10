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
from macro_risk import get_macro_risk
from db import init_db_performance_indexes
from db import get_connection
from config import (
    APPROVED_SYMBOLS,
    PRICE_RANGES,
    MARKET_OPEN_MINUTES,
    MARKET_CLOSE_MINUTES,
    DAILY_LOSS_LIMIT_PCT,
    MAX_BUYS_PER_SYMBOL_PER_DAY,
    WEBHOOK_DEDUPE_SECONDS,
    SYMBOL_MARKET_ALIGNMENT,
)

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "trades.db"
_START_TIME = datetime.now(timezone.utc)

def _init_db():
    with get_connection(DB_PATH) as con:
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
        # Operational state tables — persisted across restarts and shared between
        # gunicorn workers (Stage A: schema + startup hydration; Stage B will add
        # the write-through paths so cooldowns / recent_sells stay in sync at runtime).
        con.execute("""
            CREATE TABLE IF NOT EXISTS cooldowns (
                symbol          TEXT NOT NULL,
                action          TEXT NOT NULL,
                last_order_time TEXT NOT NULL,
                PRIMARY KEY (symbol, action)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS recent_sells (
                symbol          TEXT PRIMARY KEY,
                last_sell_time  TEXT NOT NULL,
                last_sell_price REAL NOT NULL
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS recent_webhooks (
                dedupe_key      TEXT PRIMARY KEY,
                symbol          TEXT NOT NULL,
                action          TEXT NOT NULL,
                signal_price    REAL,
                first_seen      TEXT NOT NULL
            )
        """)

        # Idempotent column additions for decision-context attribution.
        # Each new row written by log_trade / log_rejection captures the state of
        # bias / trend / momentum / macro / cluster gates at decision time so the
        # analytics layer can correlate outcomes with the context that produced them.
        existing_cols = {r[1] for r in con.execute("PRAGMA table_info(trades)").fetchall()}
        context_cols = [
            ("macro_regime",         "TEXT"),
            ("risk_multiplier",      "REAL"),
            ("market_bias",          "TEXT"),
            ("fundamental_score",    "TEXT"),
            ("risk_level",           "TEXT"),
            ("entry_quality",        "TEXT"),
            ("trend_direction",      "TEXT"),
            ("trend_strength",       "TEXT"),
            ("momentum_direction",   "TEXT"),
            ("momentum_pct",         "REAL"),
            ("correlation_cluster",  "TEXT"),
            ("cluster_exposure_pct", "REAL"),
        ]
        for col_name, col_type in context_cols:
            if col_name not in existing_cols:
                con.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")

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

try:
    init_db_performance_indexes()
    logger.info("DB performance indexes initialized")
except Exception as e:
    logger.error(f"DB performance index initialization failed: {e}")

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
            with get_connection(DB_PATH) as con:
                rows = con.execute("""
                    SELECT symbol,
                        SUM(CASE
                                WHEN LOWER(action) = 'buy'  THEN COALESCE(qty, 0)
                                WHEN LOWER(action) = 'sell' THEN -COALESCE(qty, 0)
                                ELSE 0
                            END) AS net_qty
                    FROM trades
                    WHERE order_id IS NOT NULL
                      AND order_status IN ('filled', 'partially_filled')
                    GROUP BY symbol
                    HAVING net_qty > 0
                """).fetchall()
            db_symbols = {row["symbol"] for row in rows if row["symbol"]}
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
EXECUTION_MODE = os.environ.get("EXECUTION_MODE", "live").lower().strip()
if EXECUTION_MODE not in ("live", "dry_run"):
    EXECUTION_MODE = "live"

# Correlation clusters and per-cluster exposure caps (% of cash balance).
# A new buy is blocked if the cluster's combined market value would exceed
# the limit. Symbols can appear in multiple clusters (e.g. QQQ is both
# mega_cap_tech and broad_index) — exposure to such a symbol counts against
# every cluster it belongs to.
CORRELATION_CLUSTERS = {
    "mega_cap_tech": {"AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMD", "QQQ"},
    "broad_index":   {"SPY", "QQQ", "IWM"},
    "energy":        {"CVX", "XOM"},
    "defense":       {"RTX", "LMT", "HWM", "RKLB"},
    "biotech":       {"VRTX", "MRNA", "CRSP"},
    "industrials":   {"CAT", "VRT", "GEV", "BE", "AVGO", "CRDO"},
}

CLUSTER_EXPOSURE_LIMITS = {
    "mega_cap_tech": 15.0,
    "broad_index":   12.0,
    "energy":         8.0,
    "defense":       10.0,
    "biotech":        8.0,
    "industrials":   12.0,
}

def _webhook_dedupe_key(symbol, action, price):
    """Build a loose duplicate key for near-identical TradingView alerts.

    Price is rounded to 2 decimals so tiny floating-point formatting differences
    do not bypass dedupe.
    """
    try:
        price_key = f"{float(price):.2f}"
    except Exception:
        price_key = str(price)
    return f"{symbol}:{action}:{price_key}"


def _is_duplicate_webhook(symbol, action, price):
    """Return True if the same symbol/action/rounded-price arrived recently.

    DB-backed so all gunicorn workers share dedupe state.
    """
    try:
        et = pytz.timezone("America/New_York")
        now_et = datetime.now(et)
        cutoff = now_et - timedelta(seconds=WEBHOOK_DEDUPE_SECONDS)
        key = _webhook_dedupe_key(symbol, action, price)

        with get_connection(DB_PATH) as con:
            # Opportunistic cleanup of old dedupe rows.
            con.execute(
                "DELETE FROM recent_webhooks WHERE first_seen < ?",
                (cutoff.isoformat(),),
            )

            row = con.execute(
                "SELECT first_seen FROM recent_webhooks WHERE dedupe_key = ?",
                (key,),
            ).fetchone()

            if row:
                return True

            con.execute(
                "INSERT OR REPLACE INTO recent_webhooks "
                "(dedupe_key, symbol, action, signal_price, first_seen) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, symbol, action, float(price), now_et.isoformat()),
            )
        return False

    except Exception as e:
        logger.error(f"_is_duplicate_webhook failed for {symbol}/{action}: {e}")
        return False


def _successful_buys_today(symbol):
    """Count successful BUY orders for this symbol today.

    Uses trades.db so the count is shared across all gunicorn workers.
    Counts rows that have an order_id because those represent submitted orders,
    including pending/filled states.
    """
    try:
        today = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d")
        with get_connection(DB_PATH) as con:
            row = con.execute("""
                SELECT COUNT(*)
                FROM trades
                WHERE symbol = ?
                  AND LOWER(action) = 'buy'
                  AND approved = 1
                  AND order_id IS NOT NULL
                  AND timestamp LIKE ?
            """, (symbol, f"{today}%")).fetchone()
        return int(row[0] or 0)
    except Exception as e:
        logger.error(f"_successful_buys_today failed for {symbol}: {e}")
        return 0

_last_order: dict = {}     # {(symbol, action): datetime in ET} — reset on restart
_last_sell: dict = {}      # {symbol: (datetime in ET, price)} — last successful sell, for churn prevention
_trend_table: dict = {}    # {symbol: {direction, strength, consecutive_count, last_signal, last_time}}
_signal_history: dict = {} # {symbol: [action, ...]} most recent first, max 10 — internal
_market_bias: dict = {}    # {symbol: {bias, reason, confidence}} — populated from market_context.json
_market_context_mtime: float = 0  # last seen mtime of market_context.json, used for lazy refresh
_symbol_overrides: dict = {}
_symbol_overrides_mtime: float = 0


def _load_symbol_overrides():
    """Lazy-load symbol_overrides.json.

    Allows quick operator control without code changes:
      - disabled_symbols: block both BUY and SELL
      - buy_disabled: block BUY only
      - sell_only: block BUY only, allow SELL
    """
    global _symbol_overrides_mtime, _symbol_overrides

    path = Path(__file__).parent / "symbol_overrides.json"
    default = {
        "disabled_symbols": [],
        "buy_disabled": [],
        "sell_only": [],
        "notes": {},
    }

    if not path.exists():
        _symbol_overrides = default
        return

    try:
        current_mtime = path.stat().st_mtime
        if current_mtime <= _symbol_overrides_mtime:
            return

        raw = json.loads(path.read_text())

        _symbol_overrides = {
            "disabled_symbols": [s.upper() for s in raw.get("disabled_symbols", [])],
            "buy_disabled": [s.upper() for s in raw.get("buy_disabled", [])],
            "sell_only": [s.upper() for s in raw.get("sell_only", [])],
            "notes": raw.get("notes", {}) if isinstance(raw.get("notes", {}), dict) else {},
        }
        _symbol_overrides_mtime = current_mtime

        logger.info(
            "Symbol overrides loaded: "
            f"disabled={len(_symbol_overrides['disabled_symbols'])}, "
            f"buy_disabled={len(_symbol_overrides['buy_disabled'])}, "
            f"sell_only={len(_symbol_overrides['sell_only'])}"
        )

    except Exception as e:
        logger.error(f"_load_symbol_overrides failed: {e}")
        _symbol_overrides = default


def _symbol_override_block(symbol, action):
    """Return a reason string if a symbol override blocks this signal, else None."""
    _load_symbol_overrides()

    disabled = set(_symbol_overrides.get("disabled_symbols", []))
    buy_disabled = set(_symbol_overrides.get("buy_disabled", []))
    sell_only = set(_symbol_overrides.get("sell_only", []))
    notes = _symbol_overrides.get("notes", {}) or {}

    note = notes.get(symbol) or ""

    if symbol in disabled:
        return f"symbol disabled by operator override" + (f" — {note}" if note else "")

    if action == "buy" and symbol in buy_disabled:
        return f"BUY disabled by operator override" + (f" — {note}" if note else "")

    if action == "buy" and symbol in sell_only:
        return f"symbol in sell_only mode by operator override" + (f" — {note}" if note else "")

    return None


_load_symbol_overrides()

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
    """Build trend table for every approved symbol.

    Initializes all APPROVED_SYMBOLS as neutral/weak, then overlays recent
    signal history from trades.db where available. This ensures /status and
    trend-gate logic can see all approved symbols, not only symbols with DB history.
    """
    try:
        # Start with every approved symbol so the table is complete.
        for sym in APPROVED_SYMBOLS:
            _signal_history.setdefault(sym, [])
            _trend_table[sym] = {
                "direction": "neutral",
                "strength": "weak",
                "consecutive_count": 0,
                "last_signal": None,
                "last_time": None,
            }

        approved = sorted(APPROVED_SYMBOLS)
        placeholders = ",".join("?" for _ in approved)

        with get_connection(DB_PATH) as con:
            rows = con.execute(f"""
                SELECT symbol, action, timestamp FROM (
                    SELECT symbol, action, timestamp,
                           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp DESC) AS rn
                    FROM trades
                    WHERE symbol IS NOT NULL
                      AND action IS NOT NULL
                      AND symbol IN ({placeholders})
                ) WHERE rn <= 10
                ORDER BY symbol, timestamp DESC
            """, approved).fetchall()

        history = {}
        last_time = {}

        for sym, act, ts in rows:
            if sym not in APPROVED_SYMBOLS:
                continue
            history.setdefault(sym, []).append(act)
            last_time.setdefault(sym, ts)

        for sym in APPROVED_SYMBOLS:
            actions = history.get(sym, [])
            _signal_history[sym] = actions[:10]
            entry = _compute_trend(actions)
            entry["last_time"] = last_time.get(sym)
            _trend_table[sym] = entry

        logger.info(
            f"Trend table built for {len(_trend_table)}/{len(APPROVED_SYMBOLS)} approved symbols"
        )
    except Exception as e:
        logger.error(f"_build_trend_table failed: {e}")

_build_trend_table()

def _hydrate_cooldowns():
    """Load active cooldowns from the cooldowns table into _last_order.

    Filters out entries older than the 15-min window (those are already expired
    and irrelevant). On startup this restores cooldown state across restarts and
    — once Stage B writes are in place — across gunicorn workers.
    """
    try:
        et = pytz.timezone("America/New_York")
        now_et = datetime.now(et)
        with get_connection(DB_PATH) as con:
            rows = con.execute("SELECT symbol, action, last_order_time FROM cooldowns").fetchall()
        loaded = 0
        for symbol, action, ts_str in rows:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = et.localize(ts)
                if (now_et - ts).total_seconds() < 15 * 60:
                    _last_order[(symbol, action)] = ts
                    loaded += 1
            except Exception as e:
                logger.warning(f"_hydrate_cooldowns: skipping {symbol}/{action}: {e}")
        logger.info(f"Hydrated {loaded} active cooldowns from cooldowns table (of {len(rows)} total)")
    except Exception as e:
        logger.error(f"_hydrate_cooldowns failed: {e}")

_hydrate_cooldowns()

def _hydrate_recent_sells():
    """Load recent-sell state from the recent_sells table into _last_sell.

    Filters to entries within the 30-min churn window. Restores churn-prevention
    state across restarts and (Stage B) across workers.
    """
    try:
        et = pytz.timezone("America/New_York")
        now_et = datetime.now(et)
        with get_connection(DB_PATH) as con:
            rows = con.execute("SELECT symbol, last_sell_time, last_sell_price FROM recent_sells").fetchall()
        loaded = 0
        for symbol, ts_str, price in rows:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = et.localize(ts)
                if (now_et - ts).total_seconds() < 30 * 60:
                    _last_sell[symbol] = (ts, price)
                    loaded += 1
            except Exception as e:
                logger.warning(f"_hydrate_recent_sells: skipping {symbol}: {e}")
        logger.info(f"Hydrated {loaded} recent sells from recent_sells table (of {len(rows)} total)")
    except Exception as e:
        logger.error(f"_hydrate_recent_sells failed: {e}")

_hydrate_recent_sells()


def _read_cooldown(symbol, action):
    """Return last_order_time as a tz-aware datetime for (symbol, action), or None.
    DB-backed read so all gunicorn workers see the same cooldown state."""
    try:
        et = pytz.timezone("America/New_York")
        with get_connection(DB_PATH) as con:
            row = con.execute(
                "SELECT last_order_time FROM cooldowns WHERE symbol = ? AND action = ?",
                (symbol, action),
            ).fetchone()
        if not row:
            return None
        ts = datetime.fromisoformat(row[0])
        if ts.tzinfo is None:
            ts = et.localize(ts)
        return ts
    except Exception as e:
        logger.error(f"_read_cooldown failed for {symbol}/{action}: {e}")
        return None


def _read_recent_sell(symbol):
    """Return (timestamp, price) for the last sell on `symbol`, or None.
    DB-backed read so all workers see the same churn-prevention state."""
    try:
        et = pytz.timezone("America/New_York")
        with get_connection(DB_PATH) as con:
            row = con.execute(
                "SELECT last_sell_time, last_sell_price FROM recent_sells WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        if not row:
            return None
        ts = datetime.fromisoformat(row[0])
        if ts.tzinfo is None:
            ts = et.localize(ts)
        return (ts, row[1])
    except Exception as e:
        logger.error(f"_read_recent_sell failed for {symbol}: {e}")
        return None


def _write_cooldown(symbol, action, ts):
    """Persist a cooldown entry. INSERT OR REPLACE so the same (symbol, action)
    pair is overwritten on subsequent orders."""
    try:
        with get_connection(DB_PATH) as con:
            con.execute(
                "INSERT OR REPLACE INTO cooldowns (symbol, action, last_order_time) VALUES (?, ?, ?)",
                (symbol, action, ts.isoformat()),
            )
    except Exception as e:
        logger.error(f"_write_cooldown failed for {symbol}/{action}: {e}")


def _write_recent_sell(symbol, ts, price):
    """Persist a recent-sell entry. INSERT OR REPLACE so the symbol's prior
    sell (if any) is overwritten by the new one."""
    try:
        with get_connection(DB_PATH) as con:
            con.execute(
                "INSERT OR REPLACE INTO recent_sells (symbol, last_sell_time, last_sell_price) VALUES (?, ?, ?)",
                (symbol, ts.isoformat(), price),
            )
    except Exception as e:
        logger.error(f"_write_recent_sell failed for {symbol}: {e}")


def _refresh_signal_history(symbol):
    """Re-read the last 10 signals for `symbol` from trades.db into _signal_history.

    Filters out hard-rule rejections (cooldown / churn / exposure / trend gate /
    market bias / chase prevention / market hours / circuit breaker / ghost sell)
    so trend computation reflects only signals that reached or could have reached
    the order layer. Confidence-gate rejections ARE included because they
    represent a legitimate signal that Claude evaluated — the bot filtered them
    on output quality, not on input validity.
    """
    try:
        with get_connection(DB_PATH) as con:
            rows = con.execute(
                "SELECT action FROM trades "
                "WHERE symbol = ? AND action IS NOT NULL "
                "AND (approved = 1 "
                "OR rejection_reason LIKE 'confidence_gate:%' "
                "OR rejection_reason LIKE 'trend_gate:%' "
                "OR rejection_reason LIKE 'trend_confirmation:%') "
                "ORDER BY timestamp DESC LIMIT 10",
                (symbol,),
            ).fetchall()
        _signal_history[symbol] = [r[0] for r in rows]
    except Exception as e:
        logger.warning(f"_refresh_signal_history failed for {symbol}: {e}")


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
                    "fundamental_score": entry.get("fundamental_score"),
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

def log_trade(signal, decision, order, account_state=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("signals.log", "a") as f:
        f.write(f"{timestamp} | SIGNAL: {json.dumps(signal)} | DECISION: {json.dumps(decision)} | ORDER: {json.dumps(order)}\n")
    try:
        approved = decision.get("approved", False)
        order = order or {}
        ctx = _build_decision_context(signal.get("symbol"), signal.get("action"), account_state)
        with get_connection(DB_PATH) as con:
            con.execute("""
                INSERT INTO trades (
                    timestamp, symbol, action, signal_price, approved, rejection_reason,
                    confidence, position_size_pct, stop_loss_pct, take_profit_pct,
                    order_id, order_status, qty, fill_price,
                    macro_regime, risk_multiplier, market_bias, fundamental_score, risk_level, entry_quality,
                    trend_direction, trend_strength, momentum_direction, momentum_pct,
                    correlation_cluster, cluster_exposure_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ctx["macro_regime"], ctx["risk_multiplier"],
                ctx["market_bias"], ctx["fundamental_score"],
                ctx["risk_level"], ctx["entry_quality"],
                ctx["trend_direction"], ctx["trend_strength"],
                ctx["momentum_direction"], ctx["momentum_pct"],
                ctx["correlation_cluster"], ctx["cluster_exposure_pct"],
            ))
    except Exception as e:
        logger.error(f"DB write failed for {signal.get('symbol')}: {e}")

def _build_decision_context(symbol, action, account_state=None):
    """Snapshot the decision context for a symbol/action at call time.

    Returns a dict with the 11 attribution fields. Fields whose source hasn't
    been computed yet at call time return None — that's accurate (e.g. a
    cooldown rejection fires before momentum / macro_risk are populated, so
    those fields are correctly NULL on that row).
    """
    ctx = {
        "macro_regime":         None,
        "risk_multiplier":      None,
        "market_bias":          None,
        "fundamental_score":    None,
        "risk_level":           None,
        "entry_quality":        None,
        "trend_direction":      None,
        "trend_strength":       None,
        "momentum_direction":   None,
        "momentum_pct":         None,
        "correlation_cluster":  None,
        "cluster_exposure_pct": None,
    }
    try:
        bias_entry = _market_bias.get(symbol) or {}
        ctx["market_bias"]   = bias_entry.get("bias")
        ctx["fundamental_score"]  = bias_entry.get("fundamental_score")
        ctx["risk_level"]    = bias_entry.get("risk_level")
        ctx["entry_quality"] = bias_entry.get("entry_quality")
        trend = _trend_table.get(symbol) or {}
        ctx["trend_direction"] = trend.get("direction")
        ctx["trend_strength"]  = trend.get("strength")
        if account_state:
            macro = account_state.get("macro_risk") or {}
            ctx["macro_regime"]    = macro.get("macro_regime")
            ctx["risk_multiplier"] = macro.get("risk_multiplier")
            momentum = account_state.get("momentum") or {}
            ctx["momentum_direction"] = momentum.get("direction")
            ctx["momentum_pct"]       = momentum.get("momentum_pct")
            corr = account_state.get("correlation_exposure") or []
            if corr:
                # If symbol is in multiple clusters, attribute to the highest-exposure one
                primary = max(corr, key=lambda c: c.get("exposure_pct", 0) or 0)
                ctx["correlation_cluster"]   = primary.get("cluster")
                ctx["cluster_exposure_pct"]  = primary.get("exposure_pct")
    except Exception as e:
        logger.warning(f"_build_decision_context partial failure for {symbol}: {e}")
    return ctx


def log_rejection(symbol, action, category, reason, price=None, account_state=None):
    """Persist a pre-Claude rejection to trades.db so daily_summary can count it.

    Caller is responsible for the human-readable logger.warning line; this helper
    only writes the DB row. The rejection_reason column stores '<category>: <reason>'
    so daily_summary.py can group by category prefix without parsing free-form text.

    `account_state` (optional) lets callers attach the live decision context —
    macro/momentum/correlation snapshots — so the row records WHY it was rejected
    AT THAT MOMENT, not just the gate name.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_reason = f"{category}: {reason}"
    ctx = _build_decision_context(symbol, action, account_state)
    try:
        with get_connection(DB_PATH) as con:
            con.execute(
                "INSERT INTO trades ("
                "timestamp, symbol, action, signal_price, approved, rejection_reason, "
                "macro_regime, risk_multiplier, market_bias, fundamental_score, risk_level, entry_quality, "
                "trend_direction, trend_strength, momentum_direction, momentum_pct, "
                "correlation_cluster, cluster_exposure_pct"
                ") VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    timestamp, symbol, action, price, full_reason,
                    ctx["macro_regime"], ctx["risk_multiplier"],
                    ctx["market_bias"], ctx["fundamental_score"],
                    ctx["risk_level"], ctx["entry_quality"],
                    ctx["trend_direction"], ctx["trend_strength"],
                    ctx["momentum_direction"], ctx["momentum_pct"],
                    ctx["correlation_cluster"], ctx["cluster_exposure_pct"],
                ),
            )
    except Exception as e:
        logger.error(f"log_rejection DB write failed for {symbol}: {e}")

def _open_entry_context(symbol):
    """Return the oldest currently-open buy lot context for a symbol.

    Uses FIFO-style netting from trades.db to identify open buy lots, then returns
    the oldest remaining open lot's decision context. Read-only helper for
    /positions diagnostics.
    """
    try:
        with get_connection(DB_PATH) as con:
            rows = con.execute("""
                SELECT id, timestamp, symbol, action, qty, fill_price, signal_price,
                       order_status, order_id,
                       market_bias, risk_level, entry_quality,
                       trend_direction, trend_strength,
                       momentum_direction, momentum_pct,
                       macro_regime, risk_multiplier,
                       correlation_cluster, cluster_exposure_pct
                FROM trades
                WHERE symbol = ?
                  AND order_id IS NOT NULL
                  AND order_status IN ('filled', 'partially_filled')
                  AND LOWER(action) IN ('buy', 'sell')
                  AND qty IS NOT NULL
                ORDER BY timestamp ASC, id ASC
            """, (symbol,)).fetchall()

        lots = []

        for r in rows:
            qty = float(r["qty"] or 0)
            if qty <= 0:
                continue

            action = (r["action"] or "").lower()

            if action == "buy":
                lots.append({
                    "remaining_qty": qty,
                    "row": r,
                })
                continue

            if action == "sell":
                remaining = qty
                while remaining > 0 and lots:
                    lot = lots[0]
                    matched = min(remaining, lot["remaining_qty"])
                    lot["remaining_qty"] -= matched
                    remaining -= matched
                    if lot["remaining_qty"] <= 0:
                        lots.pop(0)

        open_lots = [lot for lot in lots if lot["remaining_qty"] > 0]
        if not open_lots:
            return None

        lot = open_lots[0]
        r = lot["row"]

        entry_ts = r["timestamp"]
        holding_minutes = None
        try:
            dt = datetime.fromisoformat(str(entry_ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = pytz.timezone("America/New_York").localize(dt)
            holding_minutes = round((datetime.now(dt.tzinfo) - dt).total_seconds() / 60, 2)
        except Exception:
            pass

        return {
            "entry_timestamp": entry_ts,
            "open_lot_qty": lot["remaining_qty"],
            "entry_fill_price": r["fill_price"],
            "entry_signal_price": r["signal_price"],
            "holding_minutes": holding_minutes,
            "entry_market_bias": r["market_bias"],
            "entry_risk_level": r["risk_level"],
            "entry_quality": r["entry_quality"],
            "entry_trend_direction": r["trend_direction"],
            "entry_trend_strength": r["trend_strength"],
            "entry_momentum_direction": r["momentum_direction"],
            "entry_momentum_pct": r["momentum_pct"],
            "entry_macro_regime": r["macro_regime"],
            "entry_risk_multiplier": r["risk_multiplier"],
            "entry_correlation_cluster": r["correlation_cluster"],
            "entry_cluster_exposure_pct": r["cluster_exposure_pct"],
        }

    except Exception as e:
        logger.error(f"_open_entry_context failed for {symbol}: {e}")
        return None


def _required_buy_confirmations(symbol, account_state=None):
    """Return observe-only adaptive BUY confirmation requirement.

    This does not change trading behavior yet. It calculates what the future
    adaptive trend-confirmation threshold would be based on macro, bias, risk,
    entry quality, and market alignment.
    """
    account_state = account_state or {}

    try:
        symbol = symbol.upper()
        _load_market_context()

        bias_entry = _market_bias.get(symbol) or {}
        market_bias = bias_entry.get("bias")
        risk_level = bias_entry.get("risk_level")
        entry_quality = bias_entry.get("entry_quality")

        macro_risk = account_state.get("macro_risk") or get_macro_risk(Path(__file__).parent)
        macro_regime = macro_risk.get("macro_regime")

        alignment = account_state.get("market_alignment") or _symbol_market_alignment(symbol)
        aligned_for_buy = alignment.get("aligned_for_buy")

        required = 3
        reasons = ["base requirement is 3 BUY confirmations"]

        # Best-case fast lane: only for clean setups.
        if (
            macro_regime == "risk_on"
            and market_bias == "buy"
            and entry_quality in ("excellent", "good_on_pullbacks")
            and risk_level in ("low", "medium")
            and aligned_for_buy is True
        ):
            required = 2
            reasons.append("reduced to 2: risk_on + buy bias + high-quality entry + aligned market")

        # Risk tightening.
        if risk_level == "very_high":
            required = max(required, 4)
            reasons.append("raised to 4: very_high risk")

        if entry_quality in ("tactical_only", "conditional"):
            required = max(required, 3)
            reasons.append(f"minimum 3: entry_quality={entry_quality}")

        if entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
            required = max(required, 4)
            reasons.append(f"raised to 4: entry_quality={entry_quality}")

        if macro_regime in ("defensive", "capital_preservation"):
            required = max(required, 4)
            reasons.append(f"raised to 4: macro_regime={macro_regime}")

        if aligned_for_buy is False:
            required = max(required, 4)
            reasons.append("raised to 4: market alignment caution")

        return {
            "required_buy_confirmations": required,
            "current_rule_required_buy_confirmations": 3,
            "macro_regime": macro_regime,
            "market_bias": market_bias,
            "risk_level": risk_level,
            "entry_quality": entry_quality,
            "aligned_for_buy": aligned_for_buy,
            "observe_only": True,
            "reason": "; ".join(reasons),
        }

    except Exception as e:
        logger.error(f"_required_buy_confirmations failed for {symbol}: {e}")
        return {
            "required_buy_confirmations": 3,
            "current_rule_required_buy_confirmations": 3,
            "observe_only": True,
            "reason": f"adaptive confirmation error: {e}",
        }


def _symbol_market_alignment(symbol):
    """Return observe-only market/benchmark alignment for a symbol.

    This does not block trades. It gives /debug/symbol visibility into whether
    a symbol's BUY signals are aligned with its benchmark/index context.
    """
    try:
        symbol = symbol.upper()
        mapping = SYMBOL_MARKET_ALIGNMENT.get(symbol, {
            "cluster": "unknown",
            "benchmark": "SPY",
        })

        cluster = mapping.get("cluster", "unknown")
        benchmark = mapping.get("benchmark", "SPY")

        # Ensure market bias and trend state are fresh enough for diagnostics.
        _load_market_context()
        if benchmark not in _trend_table:
            _refresh_signal_history(benchmark)
            _trend_table[benchmark] = _compute_trend(_signal_history.get(benchmark, []))

        symbol_bias_entry = _market_bias.get(symbol) or {}
        benchmark_bias_entry = _market_bias.get(benchmark) or {}
        benchmark_trend = _trend_table.get(benchmark) or {}

        symbol_bias = symbol_bias_entry.get("bias")
        benchmark_bias = benchmark_bias_entry.get("bias")
        benchmark_direction = benchmark_trend.get("direction")
        benchmark_strength = benchmark_trend.get("strength")

        aligned = True
        reasons = []

        if symbol_bias == "avoid":
            aligned = False
            reasons.append(f"{symbol} market_bias is avoid")

        if benchmark_bias == "avoid":
            aligned = False
            reasons.append(f"benchmark {benchmark} market_bias is avoid")

        if benchmark_direction == "bearish":
            aligned = False
            reasons.append(f"benchmark {benchmark} trend is bearish")

        if benchmark_direction == "neutral" and benchmark_strength == "weak":
            # Not a hard failure yet — just a caution flag in observe-only mode.
            reasons.append(f"benchmark {benchmark} trend is neutral/weak")

        if aligned and not reasons:
            reasons.append(
                f"benchmark {benchmark} trend is {benchmark_direction}/{benchmark_strength} "
                f"and symbol bias is {symbol_bias}"
            )

        return {
            "cluster": cluster,
            "benchmark": benchmark,
            "benchmark_trend": {
                "direction": benchmark_direction,
                "strength": benchmark_strength,
                "consecutive_count": benchmark_trend.get("consecutive_count"),
            },
            "benchmark_bias": benchmark_bias,
            "symbol_bias": symbol_bias,
            "symbol_risk_level": symbol_bias_entry.get("risk_level"),
            "symbol_entry_quality": symbol_bias_entry.get("entry_quality"),
            "aligned_for_buy": aligned,
            "reason": "; ".join(reasons),
        }

    except Exception as e:
        logger.error(f"_symbol_market_alignment failed for {symbol}: {e}")
        return {
            "cluster": "unknown",
            "benchmark": None,
            "aligned_for_buy": None,
            "reason": f"alignment error: {e}",
        }


def _cluster_exposure(symbol, balance):
    """Return cluster exposure info for the symbol across current Alpaca positions."""
    if not balance:
        return []

    results = []
    try:
        positions = api.list_positions()
        position_values = {
            p.symbol: float(p.market_value)
            for p in positions
        }

        for cluster_name, members in CORRELATION_CLUSTERS.items():
            if symbol not in members:
                continue

            cluster_value = sum(
                value for sym, value in position_values.items()
                if sym in members
            )

            exposure_pct = cluster_value / balance * 100
            limit_pct = CLUSTER_EXPOSURE_LIMITS.get(cluster_name, 100.0)

            results.append({
                "cluster": cluster_name,
                "members": sorted(members),
                "current_value": round(cluster_value, 2),
                "exposure_pct": round(exposure_pct, 2),
                "limit_pct": limit_pct,
                "limit_hit": exposure_pct >= limit_pct,
            })

    except Exception as e:
        logger.error(f"_cluster_exposure failed for {symbol}: {e}")

    return results


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

    # Webhook duplicate protection: reject near-identical TradingView alerts
    # received within a short window. This is separate from order cooldowns,
    # which only start after a successful order.
    if _is_duplicate_webhook(symbol, action, price):
        logger.warning(
            f"Duplicate webhook blocked for {symbol} {action.upper()} at {price}: "
            f"same symbol/action/rounded-price within {WEBHOOK_DEDUPE_SECONDS}s"
        )
        log_rejection(
            symbol,
            action,
            "duplicate_webhook",
            f"same symbol/action/rounded-price within {WEBHOOK_DEDUPE_SECONDS}s",
            price=price,
            account_state=account_state,
        )
        return

    # Operator symbol overrides: quick no-code control during live sessions.
    override_reason = _symbol_override_block(symbol, action)
    if override_reason:
        logger.warning(
            f"Symbol override blocked {symbol} {action.upper()}: {override_reason}"
        )
        log_rejection(
            symbol,
            action,
            "symbol_override",
            override_reason,
            price=price,
            account_state=account_state,
        )
        return

    # Update trend table with this incoming signal before any pre-checks
    # (Stage C: refresh from trades.db first so all workers see the same history)
    _now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _refresh_signal_history(symbol)
    _signal_history.setdefault(symbol, []).insert(0, action)
    _signal_history[symbol] = _signal_history[symbol][:10]
    _trend_table[symbol] = {**_compute_trend(_signal_history[symbol]), "last_time": _now_ts}
    logger.debug(
        f"Trend history update for {symbol}: history={_signal_history[symbol]} "
        f"trend={_trend_table[symbol]}"
    )

    # Hard pre-check 1: market hours (9:45–15:45 ET, weekdays only)
    now_et = datetime.now(pytz.timezone("America/New_York"))
    if now_et.weekday() >= 5:
        logger.warning(f"Market hours check failed for {symbol} {action.upper()}: weekend ({now_et.strftime('%A')})")
        log_rejection(symbol, action, "market_hours", f"weekend ({now_et.strftime('%A')})", price=price, account_state=account_state)
        return
    t = now_et.hour * 60 + now_et.minute
    if not (MARKET_OPEN_MINUTES <= t < MARKET_CLOSE_MINUTES):
        logger.warning(f"Market hours check failed for {symbol} {action.upper()}: {now_et.strftime('%H:%M')} ET is outside 09:30–16:00 window")
        log_rejection(symbol, action, "market_hours", f"{now_et.strftime('%H:%M')} ET outside 09:30–16:00 window", price=price, account_state=account_state)
        return

    # Hard pre-check 2: circuit breaker (-3% daily loss limit)
    # Applies to BUY signals only. SELL signals must remain allowed so the bot
    # can reduce exposure and close risk during drawdowns.
    daily_pnl_pct = account_state.get("daily_pnl_pct", 0.0)
    if action == "buy" and daily_pnl_pct < DAILY_LOSS_LIMIT_PCT:
        logger.error(f"Circuit breaker triggered for {symbol} BUY: daily P&L is {daily_pnl_pct:.2f}% (limit: -3.0%)")
        log_rejection(symbol, action, "circuit_breaker", f"daily P&L {daily_pnl_pct:.2f}% < -3.0%", price=price, account_state=account_state)
        return

    if action == "sell":
        try:
            api.get_position(symbol)
        except Exception:
            logger.warning(f"Skipping SELL signal for {symbol} — no open position in Alpaca")
            log_rejection(symbol, action, "ghost_sell", "no open Alpaca position", price=price, account_state=account_state)
            return
    existing_position = get_position(symbol)
    if existing_position:
        account_state["current_symbol_position"] = existing_position

    # Cooldown check: skip if same symbol+action had a successful order within 15 min
    # (Stage B: DB-backed read so all workers see the same cooldown state)
    cooldown_key = (symbol, action)
    last = _read_cooldown(symbol, action)
    if last and (now_et - last).total_seconds() < 15 * 60:
        mins_remaining = int(15 * 60 - (now_et - last).total_seconds()) // 60
        logger.warning(
            f"Cooldown active for {symbol} {action.upper()}: last order at {last.strftime('%H:%M')} ET, "
            f"{mins_remaining}m remaining — skipping Claude"
        )
        log_rejection(symbol, action, "cooldown", f"{mins_remaining}m remaining (last order {last.strftime('%H:%M')} ET)", price=price, account_state=account_state)
        return

    # Sell→buy churn prevention: block buys that follow a recent sell on the same symbol
    # (Stage B: DB-backed read so all workers see the same recent-sell state)
    if action == "buy":
        last_sell = _read_recent_sell(symbol)
        if last_sell:
            last_sell_time, last_sell_price = last_sell
            elapsed_s = (now_et - last_sell_time).total_seconds()
            if elapsed_s < 30 * 60:
                mins_remaining = int(30 * 60 - elapsed_s) // 60
                logger.warning(
                    f"Sell→buy churn block for {symbol}: sold at {last_sell_time.strftime('%H:%M')} ET "
                    f"(${last_sell_price:.2f}), {mins_remaining}m remaining in 30-min window — skipping Claude"
                )
                log_rejection(symbol, action, "churn_window", f"sold at ${last_sell_price:.2f}, {mins_remaining}m remaining in 30-min window", price=price, account_state=account_state)
                return
            if last_sell_price > 0:
                price_diff_pct = abs(price - last_sell_price) / last_sell_price * 100
                if price_diff_pct < 0.5:
                    logger.warning(
                        f"Sell→buy churn block for {symbol}: signal price ${price:.2f} within "
                        f"{price_diff_pct:.2f}% of last sell price ${last_sell_price:.2f} — skipping Claude"
                    )
                    log_rejection(symbol, action, "churn_price", f"signal ${price:.2f} within {price_diff_pct:.2f}% of last sell ${last_sell_price:.2f}", price=price, account_state=account_state)
                    return

    # Daily symbol buy limit: prevent repeated same-symbol accumulation from alert storms.
    # Allows initial entry plus one add by default.
    if action == "buy":
        buys_today = _successful_buys_today(symbol)
        if buys_today >= MAX_BUYS_PER_SYMBOL_PER_DAY:
            logger.warning(
                f"Daily symbol buy limit blocked {symbol} BUY: "
                f"successful_buys_today={buys_today} >= limit={MAX_BUYS_PER_SYMBOL_PER_DAY} — skipping Claude"
            )
            log_rejection(
                symbol,
                action,
                "daily_symbol_buy_limit",
                f"successful_buys_today={buys_today} >= limit={MAX_BUYS_PER_SYMBOL_PER_DAY}",
                price=price,
                account_state=account_state,
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
                log_rejection(symbol, action, "exposure_cap", f"position ${position_value:.2f} = {exposure_pct:.2f}% of balance (limit 4.0%)", price=price, account_state=account_state)
                return

    # Correlation exposure cap: block buys when a correlated cluster is already full
    if action == "buy":
        balance = account_state.get("balance", 0)
        cluster_checks = _cluster_exposure(symbol, balance)

        for check in cluster_checks:
            if check.get("limit_hit"):
                reason = (
                    f"{check['cluster']} exposure {check['exposure_pct']:.2f}% "
                    f">= limit {check['limit_pct']:.2f}%"
                )
                logger.warning(
                    f"Correlation cap blocked {symbol} BUY: {reason} — skipping Claude"
                )
                log_rejection(symbol, action, "correlation_cap", reason, price=price, account_state=account_state)
                return

        if cluster_checks:
            account_state["correlation_exposure"] = cluster_checks

    # Trend confirmation gate: require 3 consecutive BUY alerts before allowing BUY signals through.
    # This reduces one-off TradingView/TradingPilotAI noise. SELL signals bypass this gate.
    if action == "buy":
        history = _signal_history.get(symbol, [])
        trend = _trend_table.get(symbol) or {}
        direction = trend.get("direction")
        strength = trend.get("strength")
        consecutive_count = int(trend.get("consecutive_count") or 0)

        if direction != "bullish" or consecutive_count < 3:
            logger.warning(
                f"Trend confirmation blocked {symbol} BUY: requires 3 consecutive BUY alerts; "
                f"direction={direction} strength={strength} consecutive_count={consecutive_count} — skipping Claude"
            )
            log_rejection(
                symbol,
                action,
                "trend_confirmation",
                f"requires 3 consecutive BUY alerts; direction={direction} strength={strength} count={consecutive_count}",
                price=price,
                account_state=account_state,
            )
            return

    # Macro-risk gate: regime-aware risk control before Claude
    macro_risk = get_macro_risk(Path(__file__).parent)
    account_state["macro_risk"] = macro_risk

    if action == "buy":
        if macro_risk.get("block_new_buys"):
            reason = macro_risk.get("reason", "macro regime blocks new buys")
            logger.warning(f"Macro-risk gate blocked {symbol} BUY: {reason}")
            log_rejection(symbol, action, "macro_risk", reason, price=price, account_state=account_state)
            return

        max_new_positions = macro_risk.get("max_new_positions", 8)
        open_count = account_state.get("open_position_count", 0)
        if open_count >= max_new_positions:
            reason = f"open_position_count={open_count} >= macro max_new_positions={max_new_positions}"
            logger.warning(f"Macro-risk gate blocked {symbol} BUY: {reason}")
            log_rejection(symbol, action, "macro_position_limit", reason, price=price, account_state=account_state)
            return
    # Fundamental score gate: block buys when manual/pre-market research flags weak fundamentals
    if action == "buy":
        bias_entry = _market_bias.get(symbol)
        if bias_entry:
            fundamental_score = bias_entry.get("fundamental_score")
            if fundamental_score in ("bearish", "strong_bearish"):
                reason = f"fundamental_score={fundamental_score}"
                logger.warning(
                    f"Fundamental score gate blocked {symbol} BUY: {reason} — skipping Claude"
                )
                log_rejection(
                    symbol,
                    action,
                    "fundamental_score",
                    reason,
                    price=price,
                    account_state=account_state,
                )
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
                log_rejection(symbol, action, "market_bias_avoid", f"confidence={bias_entry.get('confidence','')} reason={bias_entry.get('reason','')}", price=price, account_state=account_state)
                return
            if bias == "buy":
                account_state["market_bias"] = "buy"
            # Pass quality fields through to Claude regardless of bias direction
            if bias_entry.get("fundamental_score"):
                account_state["fundamental_score"] = bias_entry["fundamental_score"]
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
                log_rejection(symbol, action, "chase_prevention", f"entry_quality={eq} risk_level={bias_entry.get('risk_level') or '-'}", price=price, account_state=account_state)
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

    # Add-on momentum gate: for existing positions with high/very_high risk,
    # require rising short-term momentum before adding more exposure.
    # This prevents adding to already-held high-risk names when momentum is flat/falling.
    if action == "buy" and existing_position:
        risk_level = account_state.get("risk_level")
        momentum = account_state.get("momentum") or {}
        momentum_direction = momentum.get("direction")

        if risk_level in ("high", "very_high") and momentum_direction != "rising":
            logger.warning(
                f"Add-on momentum gate blocked {symbol} BUY: existing position present, "
                f"risk_level={risk_level}, momentum_direction={momentum_direction or 'unknown'} — skipping Claude"
            )
            log_rejection(
                symbol,
                action,
                "addon_momentum_gate",
                f"existing position with risk_level={risk_level} and momentum_direction={momentum_direction or 'unknown'}",
                price=price,
                account_state=account_state,
            )
            return

    account_state["trend_table"] = _trend_table
    decision = evaluate_signal(data, account_state)

    # Safety normalization: if Claude approves but the reason says to defer/wait,
    # force rejection. Prevents contradictory outputs like approved=true with
    # "recommend deferring until momentum turns rising".
    reason_text = str(decision.get("reason", "")).lower()
    defer_phrases = (
        "defer",
        "wait",
        "hold off",
        "lacks sufficient conviction",
        "not enough conviction",
        "until momentum",
        "momentum turns rising",
    )

    if action == "buy" and decision.get("approved") and any(p in reason_text for p in defer_phrases):
        logger.warning(
            f"Decision consistency guard flipped {symbol} BUY to rejected: "
            f"approved=true but reason indicated deferral"
        )
        decision["approved"] = False
        decision["confidence"] = "low"
        decision["position_size_pct"] = 0
        decision["reason"] = (
            "Rejected by consistency guard: Claude reason indicated deferral/wait despite approved=true."
        )

    order_result = None

    # Confidence gate: reject low-confidence buy signals without placing an order.
    # Persisted via log_rejection (Stage 5 categorization) so signal_history can
    # distinguish "Claude evaluated but bot filtered" from hard-rule rejections.
    if action == "buy" and decision.get("confidence") == "low":
        logger.warning(f"Low confidence BUY rejected for {symbol}: skipping order placement")
        log_rejection(
            symbol, action, "confidence_gate",
            f"Claude returned confidence=low (reason: {decision.get('reason', '')})",
            price=price, account_state=account_state,
        )
        return

    if decision.get("approved"):
        approved_reason = decision.get("reason")
        logger.info(f"APPROVED: {symbol} {action.upper()} - {approved_reason}")
        risk_multiplier = float(account_state.get("macro_risk", {}).get("risk_multiplier", 1.0))
        adjusted_position_size_pct = decision.get("position_size_pct", 1.0) * risk_multiplier

        if EXECUTION_MODE == "dry_run":
            logger.warning(
                f"DRY RUN: order not submitted for {symbol} {action.upper()} "
                f"position_size_pct={adjusted_position_size_pct:.3f}"
            )
            order_result = {
                "order_id": f"dry_run_{symbol}_{action}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "symbol": symbol,
                "side": action,
                "qty": 0,
                "stop_loss": None,
                "take_profit": None,
                "status": "dry_run",
            }
        else:
            order_result = place_order(
                symbol=symbol,
                action=action,
                position_size_pct=adjusted_position_size_pct,
                stop_loss_pct=decision.get("stop_loss_pct", 0.5),
                take_profit_pct=decision.get("take_profit_pct", 1.5),
                risk_level=account_state.get("risk_level"),
            )

        if order_result:
            if EXECUTION_MODE == "dry_run":
                logger.info(f"DRY RUN ORDER RECORDED: {order_result}")
            else:
                logger.info(f"ORDER PLACED: {order_result}")
                _last_order[cooldown_key] = now_et
                _write_cooldown(symbol, action, now_et)
                if action == "sell":
                    _last_sell[symbol] = (now_et, price)
                    _write_recent_sell(symbol, now_et, price)
        else:
            logger.error(f"Order placement failed for {symbol}")
    else:
        rejected_reason = decision.get("reason")
        logger.info(f"REJECTED: {symbol} {action.upper()} - {rejected_reason}")
    log_trade(data, decision, order_result, account_state=account_state)

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
    result = {
        "timestamp": datetime.now().isoformat(),
        "execution_mode": EXECUTION_MODE,
    }

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

    # Macro risk regime
    try:
        result["macro_risk"] = get_macro_risk(Path(__file__).parent)
    except Exception as e:
        logger.error(f"/status macro_risk error: {e}")

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

    # Correlation exposure per cluster (mega_cap_tech / broad_index / energy)
    try:
        cluster_status = {}
        for cluster_name, members in CORRELATION_CLUSTERS.items():
            value = 0.0
            held = []
            for p in api.list_positions():
                if p.symbol in members:
                    mv = float(p.market_value)
                    value += mv
                    held.append({
                        "symbol": p.symbol,
                        "value": round(mv, 2),
                    })

            exposure_pct = round(value / balance * 100, 2) if balance else None
            limit_pct = CLUSTER_EXPOSURE_LIMITS.get(cluster_name)
            cluster_status[cluster_name] = {
                "members": sorted(members),
                "held": sorted(held, key=lambda x: -x["value"]),
                "value": round(value, 2),
                "exposure_pct": exposure_pct,
                "limit_pct": limit_pct,
                "limit_hit": bool(
                    exposure_pct is not None and limit_pct is not None and exposure_pct >= limit_pct
                ),
            }

        result["correlation_exposure"] = cluster_status
    except Exception as e:
        logger.error(f"/status correlation_exposure error: {e}")

    # Pre-check state — what would block / pass right now if a buy signal arrived
    try:
        now_et = datetime.now(pytz.timezone("America/New_York"))
        t_min = now_et.hour * 60 + now_et.minute
        market_hours_open = (
            now_et.weekday() < 5
            and MARKET_OPEN_MINUTES <= t_min < MARKET_CLOSE_MINUTES
        )

        # Stage B: read cooldowns and recent_sells from DB tables so the
        # snapshot reflects state across all gunicorn workers (the in-memory
        # dicts only hold this worker's view).
        et = pytz.timezone("America/New_York")
        cooldowns = []
        churn = []
        try:
            with get_connection(DB_PATH) as con:
                cd_rows = con.execute("SELECT symbol, action, last_order_time FROM cooldowns").fetchall()
                cs_rows = con.execute("SELECT symbol, last_sell_time FROM recent_sells").fetchall()
            for sym, act, ts_str in cd_rows:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = et.localize(ts)
                    elapsed = (now_et - ts).total_seconds()
                    if elapsed < 15 * 60:
                        cooldowns.append({
                            "symbol": sym,
                            "action": act,
                            "minutes_remaining": int((15 * 60 - elapsed) // 60),
                        })
                except Exception:
                    pass
            for sym, ts_str in cs_rows:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = et.localize(ts)
                    elapsed = (now_et - ts).total_seconds()
                    if elapsed < 30 * 60:
                        churn.append(sym)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"/status DB read for pre_check_state failed: {e}")

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
            "circuit_breaker_active": (daily_pnl_pct or 0) < DAILY_LOSS_LIMIT_PCT,
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
        with get_connection(DB_PATH) as con:
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
                entry_ctx = _open_entry_context(p.symbol) or {}

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

                    # Entry-side context from the oldest currently-open FIFO lot.
                    "entry_timestamp": entry_ctx.get("entry_timestamp"),
                    "open_lot_qty": entry_ctx.get("open_lot_qty"),
                    "entry_fill_price": entry_ctx.get("entry_fill_price"),
                    "entry_signal_price": entry_ctx.get("entry_signal_price"),
                    "holding_minutes": entry_ctx.get("holding_minutes"),
                    "entry_market_bias": entry_ctx.get("entry_market_bias"),
                    "entry_risk_level": entry_ctx.get("entry_risk_level"),
                    "entry_quality": entry_ctx.get("entry_quality"),
                    "entry_trend_direction": entry_ctx.get("entry_trend_direction"),
                    "entry_trend_strength": entry_ctx.get("entry_trend_strength"),
                    "entry_momentum_direction": entry_ctx.get("entry_momentum_direction"),
                    "entry_momentum_pct": entry_ctx.get("entry_momentum_pct"),
                    "entry_macro_regime": entry_ctx.get("entry_macro_regime"),
                    "entry_risk_multiplier": entry_ctx.get("entry_risk_multiplier"),
                    "entry_correlation_cluster": entry_ctx.get("entry_correlation_cluster"),
                    "entry_cluster_exposure_pct": entry_ctx.get("entry_cluster_exposure_pct"),
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


@app.route("/debug/symbol/<symbol>", methods=["GET"])
def debug_symbol(symbol):
    validate_secret(request)

    symbol = symbol.upper()
    if symbol not in APPROVED_SYMBOLS:
        return jsonify({
            "error": "symbol not approved",
            "symbol": symbol,
            "approved_symbols": sorted(APPROVED_SYMBOLS),
        }), 400

    _load_market_context()

    now_et = datetime.now(pytz.timezone("America/New_York"))
    t_min = now_et.hour * 60 + now_et.minute
    market_hours_open = (
        now_et.weekday() < 5
        and MARKET_OPEN_MINUTES <= t_min < MARKET_CLOSE_MINUTES
    )

    result = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "now_et": now_et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "market_hours_open": market_hours_open,
    }

    # Account / circuit breaker
    try:
        state = get_mock_account_state()
        result["account"] = {
            "balance": state.get("balance"),
            "portfolio_value": state.get("portfolio_value"),
            "daily_pnl": state.get("daily_pnl"),
            "daily_pnl_pct": state.get("daily_pnl_pct"),
            "circuit_breaker_active_for_buys": (state.get("daily_pnl_pct") or 0) < DAILY_LOSS_LIMIT_PCT,
            "open_position_count": state.get("open_position_count"),
        }
    except Exception as e:
        result["account_error"] = str(e)
        state = {}

    # Alpaca live position
    try:
        pos = get_position(symbol)
        result["alpaca_position"] = pos
        result["has_live_position"] = bool(pos)
    except Exception as e:
        result["alpaca_position_error"] = str(e)

    # Trend table
    try:
        _refresh_signal_history(symbol)
        history = _signal_history.get(symbol, [])
        trend = _compute_trend(history)
        result["signal_history"] = history
        result["trend"] = trend
    except Exception as e:
        result["trend_error"] = str(e)

    # Market context
    try:
        result["market_bias"] = _market_bias.get(symbol)
    except Exception as e:
        result["market_bias_error"] = str(e)

    # Successful buys today
    try:
        result["successful_buys_today"] = _successful_buys_today(symbol)
        result["max_buys_per_symbol_per_day"] = MAX_BUYS_PER_SYMBOL_PER_DAY
        result["daily_symbol_buy_limit_hit"] = (
            result["successful_buys_today"] >= MAX_BUYS_PER_SYMBOL_PER_DAY
        )
    except Exception as e:
        result["successful_buys_today_error"] = str(e)

    # Cooldowns
    try:
        cooldowns = {}
        for action in ("buy", "sell"):
            last = _read_cooldown(symbol, action)
            if last:
                elapsed = (now_et - last).total_seconds()
                active = elapsed < 15 * 60
                cooldowns[action] = {
                    "last_order_time": last.isoformat(),
                    "active": active,
                    "minutes_remaining": int((15 * 60 - elapsed) // 60) if active else 0,
                }
            else:
                cooldowns[action] = None
        result["cooldowns"] = cooldowns
    except Exception as e:
        result["cooldown_error"] = str(e)

    # Recent sell / churn
    try:
        last_sell = _read_recent_sell(symbol)
        if last_sell:
            ts, sell_price = last_sell
            elapsed = (now_et - ts).total_seconds()
            result["recent_sell"] = {
                "last_sell_time": ts.isoformat(),
                "last_sell_price": sell_price,
                "within_30min_churn_window": elapsed < 30 * 60,
                "minutes_remaining": int((30 * 60 - elapsed) // 60) if elapsed < 30 * 60 else 0,
            }
        else:
            result["recent_sell"] = None
    except Exception as e:
        result["recent_sell_error"] = str(e)

    # Cluster exposure
    try:
        balance = float(state.get("balance") or 0)
        result["correlation_exposure"] = _cluster_exposure(symbol, balance)
    except Exception as e:
        result["correlation_exposure_error"] = str(e)

    # Macro risk
    try:
        result["macro_risk"] = get_macro_risk(Path(__file__).parent)
    except Exception as e:
        result["macro_risk_error"] = str(e)

    # Observe-only market alignment
    try:
        result["market_alignment"] = _symbol_market_alignment(symbol)
    except Exception as e:
        result["market_alignment_error"] = str(e)

    # Observe-only adaptive BUY confirmation diagnostics
    try:
        result["adaptive_buy_confirmation"] = _required_buy_confirmations(symbol, result)
    except Exception as e:
        result["adaptive_buy_confirmation_error"] = str(e)

    # High-level buy block reasons
    buy_blocks = []

    override_reason = _symbol_override_block(symbol, "buy")
    if override_reason:
        buy_blocks.append("symbol_override")

    if not market_hours_open:
        buy_blocks.append("market_hours")

    acct = result.get("account") or {}
    if acct.get("circuit_breaker_active_for_buys"):
        buy_blocks.append("circuit_breaker")

    trend = result.get("trend") or {}
    if trend.get("direction") != "bullish" or int(trend.get("consecutive_count") or 0) < 3:
        buy_blocks.append("trend_confirmation")

    bias = result.get("market_bias") or {}

    if bias.get("bias") == "avoid":
        buy_blocks.append("market_bias_avoid")

    fundamental_score = bias.get("fundamental_score")

    if fundamental_score in ("bearish", "strong_bearish"):
        buy_blocks.append("fundamental_score")

    if bias.get("entry_quality") in ("do_not_chase", "avoid_chasing"):
        buy_blocks.append("chase_prevention")

    if result.get("daily_symbol_buy_limit_hit"):
        buy_blocks.append("daily_symbol_buy_limit")

    macro = result.get("macro_risk") or {}
    if macro.get("block_new_buys"):
        buy_blocks.append("macro_risk")

    for c in result.get("correlation_exposure") or []:
        if c.get("limit_hit"):
            buy_blocks.append(f"correlation_cap:{c.get('cluster')}")

    result["would_block_buy_because"] = buy_blocks
    result["buy_would_pass_known_prechecks"] = len(buy_blocks) == 0

    return jsonify(result), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
