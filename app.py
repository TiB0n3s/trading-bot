import os
import json
import sqlite3
import logging
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import pytz
import time
from setup_policy import evaluate_setup_policy
from pathlib import Path
from live_features import build_snapshot
from flask import Flask, request, jsonify, abort
from indicator_state import (
    compute_indicator_state,
    is_fast_lane_buy_flip,
    is_fast_lane_sell_flip,
)
from session_momentum import (
    init_session_momentum_table,
    get_latest_session_momentum,
)
from decision_engine import evaluate_signal, get_mock_account_state
from broker import place_order, get_account, get_position, api
from macro_risk import get_macro_risk
from decision_thresholds import PREDICTION_GATE_THRESHOLDS
from runtime_config import (
    EXECUTION_MODE,
    LIVE_TRADING_ENABLED,
    CASH_SAFE_SYMBOLS,
    CASH_SAFE_MAX_OPEN_POSITIONS,
    CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY,
    MAX_LIVE_ORDER_DOLLARS,
    CASH_SAFE_MAX_ORDER_DOLLARS,
    is_cash_mode,
    is_cash_safe_mode,
    public_runtime_config,
)
from symbols_config import (
    APPROVED_SYMBOLS,
    CORRELATION_CLUSTERS,
    CLUSTER_EXPOSURE_LIMITS,
    PRICE_RANGES,
)
from market_time import now_et, is_market_hours, market_session
from db import init_db_performance_indexes
from db import (
    DB_PATH,
    get_connection,
    ensure_recent_favorable_setups_table,
    upsert_recent_favorable_setup,
    get_recent_favorable_setup,
    prune_recent_favorable_setups,
)
from config import (
    MARKET_OPEN_MINUTES,
    MARKET_CLOSE_MINUTES,
    DAILY_LOSS_LIMIT_PCT,
    MAX_BUYS_PER_SYMBOL_PER_DAY,
    WEBHOOK_DEDUPE_SECONDS,
    SYMBOL_MARKET_ALIGNMENT,
)
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "paper").strip().lower()
IS_PAPER_MODE = EXECUTION_MODE == "paper"

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "trades.db"
_START_TIME = datetime.now(timezone.utc)
ENFORCE_SETUP_POLICY_BLOCKS = True
ENFORCE_PREDICTION_BLOCKS = True
ENFORCE_PREDICTION_WATCH_IN_CASH = True
ENFORCE_SESSION_MOMENTUM_GATE = os.getenv(
    "ENFORCE_SESSION_MOMENTUM_GATE",
    "false"
).strip().lower() in ("1", "true", "yes", "on")
SIGNAL_WORKER_COUNT = int(os.environ.get("SIGNAL_WORKER_COUNT", "3"))
_signal_executor = ThreadPoolExecutor(
    max_workers=SIGNAL_WORKER_COUNT,
    thread_name_prefix="signal-worker",
)

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
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT UNIQUE NOT NULL,
                received_at TEXT NOT NULL,
                symbol TEXT,
                action TEXT,
                signal_price REAL,
                source TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'received',
                queued_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                order_id TEXT,
                client_order_id TEXT,
                failure_reason TEXT
            )
        """)

        existing_webhook_cols = {
        r[1] for r in con.execute("PRAGMA table_info(webhook_events)").fetchall()
    }
    webhook_context_cols = [
        ("queued_at", "TEXT"),
        ("started_at", "TEXT"),
        ("finished_at", "TEXT"),
        ("order_id", "TEXT"),
        ("client_order_id", "TEXT"),
        ("failure_reason", "TEXT"),

    ]
    for col_name, col_type in webhook_context_cols:
        if col_name not in existing_webhook_cols:
            con.execute(f"ALTER TABLE webhook_events ADD COLUMN {col_name} {col_type}")

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
            ("market_bias_effective", "TEXT"),
            ("market_bias_override_reason", "TEXT"),
            ("fundamental_score",    "TEXT"),
            ("risk_level",           "TEXT"),
            ("entry_quality",        "TEXT"),
            ("trend_direction",      "TEXT"),
            ("trend_strength",       "TEXT"),
            ("momentum_direction",   "TEXT"),
            ("session_trend_label", "TEXT"),
            ("session_trend_score", "REAL"),
            ("session_return_pct", "REAL"),
            ("session_momentum_5m_pct", "REAL"),
            ("session_momentum_15m_pct", "REAL"),
            ("session_momentum_30m_pct", "REAL"),
            ("session_distance_from_vwap_pct", "REAL"),
            ("session_momentum_reason", "TEXT"),
            ("momentum_pct",         "REAL"),
            ("prediction_score", "REAL"),
            ("prediction_decision", "TEXT"),
            ("prediction_reason", "TEXT"),
            ("correlation_cluster",  "TEXT"),
            ("cluster_exposure_pct", "REAL"),
            ("setup_label",          "TEXT"),
            ("setup_policy_action",  "TEXT"),
            ("setup_policy_reason",  "TEXT"),
            ("setup_confidence_adjustment", "REAL"),
            ("setup_size_multiplier", "REAL"),
        ]
        for col_name, col_type in context_cols:
            if col_name not in existing_cols:
                con.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")

_init_db()

RECENT_FAVORABLE_SETUP_TTL_MINUTES = 15

ensure_recent_favorable_setups_table()
prune_recent_favorable_setups(RECENT_FAVORABLE_SETUP_TTL_MINUTES)

try:
    init_session_momentum_table()
except Exception as e:
    logger.error(f"Session momentum table initialization failed: {e}")

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

def _observe_setup_policy(setup_label: str | None) -> dict:
    """
    Observe-only setup policy evaluation.

    This computes what setup_policy.py *would* do, but does not change approval,
    confidence, or position sizing yet.
    """
    try:
        policy = evaluate_setup_policy(setup_label)
    except Exception as e:
        logger.warning(f"setup policy evaluation failed for label={setup_label!r}: {e}")
        return {
            "setup_policy_action": "error",
            "setup_confidence_adjustment": 0,
            "setup_size_multiplier": 1.0,
            "reason": "setup_policy:error",
        }

    return policy

def _build_setup_observation(symbol, action, price, account_state):
    """
    Observe-only setup snapshot + setup policy evaluation.

    Returns a dict with setup fields. Fail-open: never blocks trading here.
    """
    if action != "buy":
        return {
            "setup_label": None,
            "setup_policy_action": "not_applicable",
            "setup_policy_reason": "setup_policy:not_applicable:sell",
            "setup_confidence_adjustment": 0,
            "setup_size_multiplier": 1.0,
            "setup_score": None,
            "setup_confidence": None,
            "setup_key": None,
            "setup_rationale": None,
        }

    try:
        snapshot = build_snapshot(symbol)
        setup_label = snapshot.get("setup_label")
        setup_policy = _observe_setup_policy(setup_label)

        logger.info(
            "Setup policy evaluated: "
            f"symbol={symbol} "
            f"setup_label={setup_label} "
            f"policy_action={setup_policy.get('setup_policy_action')} "
            f"confidence_adjustment={setup_policy.get('setup_confidence_adjustment')} "
            f"size_multiplier={setup_policy.get('setup_size_multiplier')} "
            f"reason={setup_policy.get('reason')}"
        )

        return {
            "setup_label": setup_label,
            "setup_policy_action": setup_policy.get("setup_policy_action"),
            "setup_policy_reason": setup_policy.get("reason"),
            "setup_confidence_adjustment": setup_policy.get("setup_confidence_adjustment"),
            "setup_size_multiplier": setup_policy.get("setup_size_multiplier"),
            "setup_score": snapshot.get("setup_score"),
            "setup_confidence": snapshot.get("setup_confidence"),
            "setup_key": snapshot.get("setup_key"),
            "setup_rationale": snapshot.get("setup_rationale"),
        }

    except Exception as e:
        logger.warning(f"setup observe-only snapshot failed for {symbol}: {e}")
        return {
            "setup_label": None,
            "setup_policy_action": "error",
            "setup_policy_reason": f"setup_policy:error:{e}",
            "setup_confidence_adjustment": 0,
            "setup_size_multiplier": 1.0,
            "setup_score": None,
            "setup_confidence": None,
            "setup_key": None,
            "setup_rationale": None,
        }

def _is_favorable_setup_label(setup_label: str | None) -> bool:
    return setup_label in {
        "confirmed_near_vwap_recovery",
        "near_vwap_weak_strength_followthrough",
        "oversold_weak_bounce_watch",
        "above_vwap_strength_continuation",
    }


def _remember_favorable_setup(symbol: str, setup_obs: dict | None) -> None:
    if not symbol or not setup_obs:
        return

    setup_label = setup_obs.get("setup_label")
    setup_policy_action = setup_obs.get("setup_policy_action")

    if setup_policy_action == "boost" or _is_favorable_setup_label(setup_label):
        upsert_recent_favorable_setup(
            symbol=symbol,
            observed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            setup_label=setup_label,
            setup_policy_action=setup_policy_action,
        )


def _get_recent_favorable_setup(symbol: str) -> dict | None:
    row = get_recent_favorable_setup(
        symbol=symbol,
        ttl_minutes=RECENT_FAVORABLE_SETUP_TTL_MINUTES,
    )
    if not row:
        return None

    observed_at_raw = row["observed_at"]
    try:
        observed_at = datetime.strptime(observed_at_raw, "%Y-%m-%d %H:%M:%S")
        age_minutes = round((datetime.now() - observed_at).total_seconds() / 60.0, 2)
    except Exception:
        age_minutes = None

    return {
        "setup_label": row["setup_label"],
        "setup_policy_action": row["setup_policy_action"],
        "observed_at": observed_at_raw,
        "age_minutes": age_minutes,
    }

def evaluate_prediction_gate(
    *,
    trend_direction,
    trend_strength,
    market_bias,
    setup_label,
    setup_policy_action,
    momentum_direction,
    momentum_pct,
    consecutive_buy_count,
    recent_favorable_setup=None,
):
    score = 0
    reasons = []

    if trend_direction == "bullish":
        score += 2
        reasons.append("bullish_trend")
    elif trend_direction == "neutral":
        score += 0
    else:
        score -= 2
        reasons.append("non_bullish_trend")

    if trend_strength == "confirmed":
        score += 2
        reasons.append("confirmed_trend")
    elif trend_strength == "developing":
        score += 1
        reasons.append("developing_trend")
    else:
        score -= 1
        reasons.append("weak_trend")

    if market_bias == "buy":
        score += 2
        reasons.append("market_bias_buy")
    elif market_bias == "neutral":
        score += 0
    elif market_bias == "avoid":
        score -= 3
        reasons.append("market_bias_avoid")

    if setup_policy_action == "boost":
        score += 2
        reasons.append("setup_policy_boost")
    elif setup_policy_action == "neutral":
        score += 0
    elif setup_policy_action == "block":
        score -= 4
        reasons.append("setup_policy_block")

    if setup_label in {
        "confirmed_near_vwap_recovery",
        "near_vwap_weak_strength_followthrough",
        "oversold_weak_bounce_watch",
    }:
        score += 1
        reasons.append("favorable_setup_label")
    elif setup_label in {
        "avoid_stretched_above_vwap_strength",
        "avoid_far_below_vwap_chase",
        "avoid_below_vwap_weak_drift",
    }:
        score -= 3
        reasons.append("avoid_setup_label")

    if recent_favorable_setup:
        recent_label = recent_favorable_setup.get("setup_label")
        recent_action = recent_favorable_setup.get("setup_policy_action")

        if recent_action == "boost":
            score += 1
            reasons.append("recent_boost_memory")

        if _is_favorable_setup_label(recent_label):
            score += 1
            reasons.append("recent_favorable_setup_memory")

    if momentum_direction == "rising":
        score += 1
        reasons.append("rising_momentum")
    elif momentum_direction == "falling":
        score -= 1
        reasons.append("falling_momentum")

    try:
        momentum_value = float(momentum_pct) if momentum_pct is not None else None
    except (TypeError, ValueError):
        momentum_value = None

    if momentum_value is not None:
        if momentum_value > 0.15:
            score += 1
            reasons.append("positive_momentum_pct")
        elif momentum_value < -0.15:
            score -= 1
            reasons.append("negative_momentum_pct")

    if consecutive_buy_count >= 3:
        score += 2
        reasons.append("three_plus_consecutive_buys")
    elif consecutive_buy_count == 2:
        score += 1
        reasons.append("two_consecutive_buys")
    elif consecutive_buy_count <= 0:
        score -= 1
        reasons.append("no_consecutive_buy_confirmation")

    if score >= PREDICTION_GATE_THRESHOLDS["pass_min_score"]:
        decision = "pass"
    elif score >= PREDICTION_GATE_THRESHOLDS["watch_min_score"]:
        decision = "watch"
    else:
        decision = "block"

    return {
        "prediction_score": score,
        "prediction_decision": decision,
        "prediction_reason": ",".join(reasons),
    }

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "changeme")

_last_order: dict = {}
_last_sell: dict = {}
_trend_table: dict = {}
_signal_history: dict = {}
_market_bias: dict = {}
_market_context_mtime: float = 0

def _reject_current_signal(category, reason, level="warning"):
    if level == "error":
        logger.error(f"{category} blocked {symbol} {action.upper()}: {reason}")
    elif level == "info":
        logger.info(f"{category} blocked {symbol} {action.upper()}: {reason}")
    else:
        logger.warning(f"{category} blocked {symbol} {action.upper()}: {reason}")

    log_rejection(
        symbol,
        action,
        category,
        reason,
        price=price,
        account_state=account_state,
    )
    return True

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
    state = compute_indicator_state(
        recent_actions,
        buy_flip_min=2,
        sell_flip_min=2,
        confirmed_min=3,
    )
    return {
        "direction": state["direction"],
        "strength": state["strength"],
        "consecutive_count": state["consecutive_count"],
        "last_signal": state["last_signal"],
        "flip_event": state["flip_event"],
        "confirmed_entry": state["confirmed_entry"],
        "confirmed_exit": state["confirmed_exit"],
        "bullish_candidate": state["bullish_candidate"],
        "bearish_candidate": state["bearish_candidate"],
        "previous_opposite_count": state["previous_opposite_count"],
    }

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
        current_et = now_et()
        with get_connection(DB_PATH) as con:
            rows = con.execute("SELECT symbol, action, last_order_time FROM cooldowns").fetchall()
        loaded = 0
        for symbol, action, ts_str in rows:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = et.localize(ts)
                if (current_et - ts).total_seconds() < 15 * 60:
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
        current_et = now_et()
        with get_connection(DB_PATH) as con:
            rows = con.execute("SELECT symbol, last_sell_time, last_sell_price FROM recent_sells").fetchall()
        loaded = 0
        for symbol, ts_str, price in rows:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = et.localize(ts)
                if (current_et - ts).total_seconds() < 30 * 60:
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
                    "avoid_type": entry.get("avoid_type"),
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

def _make_dedupe_key(data):
    """Create a stable dedupe key for repeated webhook deliveries.

    Prefer explicit alert IDs when TradingView provides them; otherwise fall back
    to a deterministic hash of the normalized signal fields.
    """
    import hashlib

    explicit = (
        data.get("alert_id")
        or data.get("id")
        or data.get("uuid")
        or data.get("webhook_id")
    )
    if explicit:
        return f"explicit:{str(explicit).strip()}"

    normalized = {
        "symbol": str(data.get("symbol", "")).upper(),
        "action": str(data.get("action", "")).lower(),
        "price": str(data.get("price", "")),
        "source": str(data.get("source", "")),
        "timestamp": str(
            data.get("timestamp")
            or data.get("time")
            or data.get("alert_time")
            or data.get("alert_timestamp")
            or ""
        ),
    }

    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return "hash:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _record_webhook_event(dedupe_key, data):
    """Persist webhook receipt.

    Returns True if this is a new event, False if it is a duplicate inside the
    active dedupe table.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            """
            DELETE FROM webhook_events
            WHERE received_at < datetime('now', ?)
            """,
            (f"-{WEBHOOK_DEDUPE_SECONDS} seconds",),
        )
        con.execute(
            """
            INSERT INTO webhook_events (
                dedupe_key, received_at, symbol, action, signal_price, source,
                payload_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'received')
            """,
            (
                dedupe_key,
                timestamp,
                str(data.get("symbol", "")).upper(),
                str(data.get("action", "")).lower(),
                data.get("price"),
                data.get("source"),
                json.dumps(data, sort_keys=True),
            ),
        )
        con.commit()
        con.close()
        return True
    except sqlite3.IntegrityError:
        try:
            con.close()
        except Exception:
            pass
        return False
    except Exception as e:
        logger.error(f"Webhook dedupe persistence failed: {e}")
        try:
            con.close()
        except Exception:
            pass
        # Fail open so a DB hiccup does not drop a legitimate sell/risk-reducing signal.
        return True


def _mark_webhook_event_status(
    dedupe_key,
    status,
    order_id=None,
    client_order_id=None,
    failure_reason=None,
):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        time_column = None
        if status == "queued":
            time_column = "queued_at"
        elif status in ("processing", "started"):
            time_column = "started_at"
        elif status in (
            "processed",
            "rejected",
            "submitted",
            "submit_failed",
            "duplicate_ignored",
            "error",
        ):
            time_column = "finished_at"

        assignments = ["status = ?"]
        params = [status]

        if time_column:
            assignments.append(f"{time_column} = ?")
            params.append(now)

        if order_id is not None:
            assignments.append("order_id = ?")
            params.append(order_id)

        if client_order_id is not None:
            assignments.append("client_order_id = ?")
            params.append(client_order_id)

        if failure_reason is not None:
            assignments.append("failure_reason = ?")
            params.append(str(failure_reason)[:500])

        params.append(dedupe_key)

        con = sqlite3.connect(DB_PATH)
        con.execute(
            f"UPDATE webhook_events SET {', '.join(assignments)} WHERE dedupe_key = ?",
            params,
        )
        con.commit()
        con.close()
    except Exception as e:
        logger.warning(f"Failed to update webhook event status for {dedupe_key}: {e}")

def validate_secret(req):
    secret = req.args.get("secret", "")
    if secret != WEBHOOK_SECRET:
        logger.warning(f"Invalid secret from {req.remote_addr}")
        abort(401)

def log_trade(signal, decision, order, account_state=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open("signals.log", "a") as f:
        line = (
            f"{timestamp} | SIGNAL: {json.dumps(signal)} | "
            f"DECISION: {json.dumps(decision)} | ORDER: {json.dumps(order)}"
        )
        f.write(line + "\n")

    try:
        approved = decision.get("approved", False)
        order = order or {}
        ctx = _build_decision_context(
            signal.get("symbol"),
            signal.get("action"),
            account_state,
        )
        setup_obs = (account_state or {}).get("setup_observation") or {}
        prediction_gate = (account_state or {}).get("prediction_gate") or {}

        columns = [
            "timestamp",
            "symbol",
            "action",
            "signal_price",
            "approved",
            "rejection_reason",
            "confidence",
            "position_size_pct",
            "stop_loss_pct",
            "take_profit_pct",
            "order_id",
            "order_status",
            "qty",
            "fill_price",
            "macro_regime",
            "risk_multiplier",
            "market_bias",
            "market_bias_effective",
            "market_bias_override_reason",
            "fundamental_score",
            "risk_level",
            "entry_quality",
            "trend_direction",
            "trend_strength",
            "momentum_direction",
            "momentum_pct",
            "session_trend_label",
            "session_trend_score",
            "session_return_pct",
            "session_momentum_5m_pct",
            "session_momentum_15m_pct",
            "session_momentum_30m_pct",
            "session_distance_from_vwap_pct",
            "session_momentum_reason",
            "prediction_score",
            "prediction_decision",
            "prediction_reason",
            "correlation_cluster",
            "cluster_exposure_pct",
            "setup_label",
            "setup_policy_action",
            "setup_policy_reason",
            "setup_confidence_adjustment",
            "setup_size_multiplier",
        ]

        values = [
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
            ctx["macro_regime"],
            ctx["risk_multiplier"],
            ctx["market_bias"],
            ctx["market_bias_effective"],
            ctx["market_bias_override_reason"],
            ctx["fundamental_score"],
            ctx["risk_level"],
            ctx["entry_quality"],
            ctx["trend_direction"],
            ctx["trend_strength"],
            ctx["momentum_direction"],
            ctx["momentum_pct"],
            ctx["session_trend_label"],
            ctx["session_trend_score"],
            ctx["session_return_pct"],
            ctx["session_momentum_5m_pct"],
            ctx["session_momentum_15m_pct"],
            ctx["session_momentum_30m_pct"],
            ctx["session_distance_from_vwap_pct"],
            ctx["session_momentum_reason"],
            prediction_gate.get("prediction_score"),
            prediction_gate.get("prediction_decision"),
            prediction_gate.get("prediction_reason"),
            ctx["correlation_cluster"],
            ctx["cluster_exposure_pct"],
            setup_obs.get("setup_label"),
            setup_obs.get("setup_policy_action"),
            setup_obs.get("setup_policy_reason"),
            setup_obs.get("setup_confidence_adjustment"),
            setup_obs.get("setup_size_multiplier"),
        ]

        placeholders = ", ".join(["?"] * len(values))
        col_sql = ", ".join(columns)

        with get_connection(DB_PATH) as con:
            con.execute(
                f"INSERT INTO trades ({col_sql}) VALUES ({placeholders})",
                values,
            )

    except Exception as e:
        logger.error(f"DB write failed for {signal.get('symbol')}: {e}")


def _build_decision_context(symbol, action, account_state=None):
    """Snapshot the decision context for a symbol/action at call time.

    Returns attribution fields. Fields whose source hasn't been computed yet
    at call time return None — that's accurate for early pre-check rejections.
    """
    ctx = {
        "macro_regime": None,
        "risk_multiplier": None,
        "market_bias": None,
        "market_bias_effective": None,
        "market_bias_override_reason": None,
        "fundamental_score": None,
        "risk_level": None,
        "entry_quality": None,
        "trend_direction": None,
        "trend_strength": None,
        "momentum_direction": None,
        "momentum_pct": None,
        "session_trend_label": None,
        "session_trend_score": None,
        "session_return_pct": None,
        "session_momentum_5m_pct": None,
        "session_momentum_15m_pct": None,
        "session_momentum_30m_pct": None,
        "session_distance_from_vwap_pct": None,
        "session_momentum_reason": None,
        "correlation_cluster": None,
        "cluster_exposure_pct": None,
    }

    try:
        bias_entry = _market_bias.get(symbol) or {}
        ctx["market_bias"] = bias_entry.get("bias")
        ctx["fundamental_score"] = bias_entry.get("fundamental_score")
        ctx["risk_level"] = bias_entry.get("risk_level")
        ctx["entry_quality"] = bias_entry.get("entry_quality")

        trend = _trend_table.get(symbol) or {}
        ctx["trend_direction"] = trend.get("direction")
        ctx["trend_strength"] = trend.get("strength")

        if account_state:
            macro = account_state.get("macro_risk") or {}
            ctx["macro_regime"] = macro.get("macro_regime")
            ctx["risk_multiplier"] = macro.get("risk_multiplier")
            ctx["market_bias_effective"] = account_state.get("market_bias_effective")
            ctx["market_bias_override_reason"] = account_state.get("market_bias_override_reason")

            momentum = account_state.get("momentum") or {}
            ctx["momentum_direction"] = momentum.get("direction")
            ctx["momentum_pct"] = momentum.get("momentum_pct")

            session_momentum = account_state.get("session_momentum") or {}
            ctx["session_trend_label"] = session_momentum.get("trend_label")
            ctx["session_trend_score"] = session_momentum.get("trend_score")
            ctx["session_return_pct"] = session_momentum.get("session_return_pct")
            ctx["session_momentum_5m_pct"] = session_momentum.get("momentum_5m_pct")
            ctx["session_momentum_15m_pct"] = session_momentum.get("momentum_15m_pct")
            ctx["session_momentum_30m_pct"] = session_momentum.get("momentum_30m_pct")
            ctx["session_distance_from_vwap_pct"] = session_momentum.get("distance_from_vwap_pct")
            ctx["session_momentum_reason"] = session_momentum.get("reason")

            corr = account_state.get("correlation_exposure") or []
            if corr:
                # If symbol is in multiple clusters, attribute to the highest-exposure one.
                primary = max(corr, key=lambda c: c.get("exposure_pct", 0) or 0)
                ctx["correlation_cluster"] = primary.get("cluster")
                ctx["cluster_exposure_pct"] = primary.get("exposure_pct")

    except Exception as e:
        logger.warning(f"_build_decision_context partial failure for {symbol}: {e}")

    return ctx

def log_rejection(symbol, action, category, reason, price=None, account_state=None):
    """Persist a pre-Claude rejection to trades.db so reports can count it."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_reason = f"{category}: {reason}"
    ctx = _build_decision_context(symbol, action, account_state)
    setup_obs = (account_state or {}).get("setup_observation") or {}
    prediction_gate = (account_state or {}).get("prediction_gate") or {}

    columns = [
        "timestamp",
        "symbol",
        "action",
        "signal_price",
        "approved",
        "rejection_reason",
        "macro_regime",
        "risk_multiplier",
        "market_bias",
        "market_bias_effective",
        "market_bias_override_reason",
        "fundamental_score",
        "risk_level",
        "entry_quality",
        "trend_direction",
        "trend_strength",
        "momentum_direction",
        "momentum_pct",
        "session_trend_label",
        "session_trend_score",
        "session_return_pct",
        "session_momentum_5m_pct",
        "session_momentum_15m_pct",
        "session_momentum_30m_pct",
        "session_distance_from_vwap_pct",
        "session_momentum_reason",
        "prediction_score",
        "prediction_decision",
        "prediction_reason",
        "correlation_cluster",
        "cluster_exposure_pct",
        "setup_label",
        "setup_policy_action",
        "setup_policy_reason",
        "setup_confidence_adjustment",
        "setup_size_multiplier",
    ]

    values = [
        timestamp,
        symbol,
        action,
        price,
        0,
        full_reason,
        ctx["macro_regime"],
        ctx["risk_multiplier"],
        ctx["market_bias"],
        ctx["market_bias_effective"],
        ctx["market_bias_override_reason"],
        ctx["fundamental_score"],
        ctx["risk_level"],
        ctx["entry_quality"],
        ctx["trend_direction"],
        ctx["trend_strength"],
        ctx["momentum_direction"],
        ctx["momentum_pct"],
        ctx["session_trend_label"],
        ctx["session_trend_score"],
        ctx["session_return_pct"],
        ctx["session_momentum_5m_pct"],
        ctx["session_momentum_15m_pct"],
        ctx["session_momentum_30m_pct"],
        ctx["session_distance_from_vwap_pct"],
        ctx["session_momentum_reason"],
        prediction_gate.get("prediction_score"),
        prediction_gate.get("prediction_decision"),
        prediction_gate.get("prediction_reason"),
        ctx["correlation_cluster"],
        ctx["cluster_exposure_pct"],
        setup_obs.get("setup_label"),
        setup_obs.get("setup_policy_action"),
        setup_obs.get("setup_policy_reason"),
        setup_obs.get("setup_confidence_adjustment"),
        setup_obs.get("setup_size_multiplier"),
    ]

    placeholders = ", ".join(["?"] * len(values))
    col_sql = ", ".join(columns)

    try:
        with get_connection(DB_PATH) as con:
            con.execute(
                f"INSERT INTO trades ({col_sql}) VALUES ({placeholders})",
                values,
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

def _required_sell_confirmations(symbol, account_state=None):
    return {
        "required_sell_confirmations": 2,
        "current_rule_required_sell_confirmations": 2,
        "observe_only": False,
        "reason": "base requirement is 2 SELL confirmations",
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

def _live_bias_override(symbol, bias_entry, trend, setup_obs, prediction_gate, momentum):
    """
    Convert pre-market bias into an effective intraday bias using live evidence.

    This helper does not override hard risk controls. It only decides whether
    a pre-market bias should remain active, soften, or be downgraded/upgraded
    based on trend, setup, prediction score, and momentum.
    """
    bias_entry = bias_entry or {}
    trend = trend or {}
    setup_obs = setup_obs or {}
    prediction_gate = prediction_gate or {}
    momentum = momentum or {}

    bias = bias_entry.get("bias")
    avoid_type = (bias_entry.get("avoid_type") or "").lower()
    fundamental_score = bias_entry.get("fundamental_score")
    entry_quality = bias_entry.get("entry_quality")

    trend_direction = trend.get("direction")
    trend_strength = trend.get("strength")
    consecutive_count = int(trend.get("consecutive_count") or 0)
    last_signal = trend.get("last_signal")

    setup_action = setup_obs.get("setup_policy_action")
    setup_label = setup_obs.get("setup_label")

    prediction_score = int(prediction_gate.get("prediction_score") or 0)
    prediction_decision = prediction_gate.get("prediction_decision")

    momentum_direction = momentum.get("direction")

    # Hard avoid remains hard. This includes missing avoid_type, because
    # parse_market_brief.py conservatively defaults avoid to hard unless
    # the brief explicitly marks it soft.
    if bias == "avoid" and avoid_type != "soft":
        return {
            "effective_bias": "avoid_hard",
            "allow_buy": False,
            "confidence_adjustment": -30,
            "reason": "hard pre-market avoid remains active",
        }

    # Weak fundamentals should not be overridden by live tape alone.
    if fundamental_score in ("bearish", "strong_bearish"):
        return {
            "effective_bias": "avoid_hard",
            "allow_buy": False,
            "confidence_adjustment": -30,
            "reason": f"fundamental_score={fundamental_score} remains hard block",
        }

    # Poor/chase entry-quality remains a hard no. The existing chase gate should
    # normally catch this too; this keeps attribution consistent.
    if entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
        return {
            "effective_bias": "avoid_hard",
            "allow_buy": False,
            "confidence_adjustment": -30,
            "reason": f"entry_quality={entry_quality} remains hard block",
        }

    live_positive = (
        trend_direction == "bullish"
        and last_signal == "buy"
        and consecutive_count >= 3
        and momentum_direction == "rising"
        and prediction_decision == "pass"
        and prediction_score >= 6
        and setup_action in ("boost", "allow", "neutral")
    )

    live_strong_positive = (
        live_positive
        and trend_strength in ("developing", "confirmed")
        and prediction_score >= 8
        and setup_action in ("boost", "allow")
    )

    live_negative = (
        trend_direction == "bearish"
        or momentum_direction == "falling"
        or prediction_decision == "block"
        or setup_action == "block"
    )

    if bias == "avoid" and avoid_type == "soft":
        if live_strong_positive:
            return {
                "effective_bias": "live_override_buy",
                "allow_buy": True,
                "confidence_adjustment": -5,
                "reason": (
                    "soft avoid overridden by live confirmation: "
                    f"trend={trend_direction}/{trend_strength}, "
                    f"count={consecutive_count}, "
                    f"setup={setup_label}, "
                    f"setup_action={setup_action}, "
                    f"prediction_score={prediction_score}, "
                    f"momentum={momentum_direction}"
                ),
            }

        return {
            "effective_bias": "avoid_soft",
            "allow_buy": False,
            "confidence_adjustment": -15,
            "reason": (
                "soft avoid still active; requires stronger live confirmation: "
                f"trend={trend_direction}/{trend_strength}, "
                f"count={consecutive_count}, "
                f"setup_action={setup_action}, "
                f"prediction_score={prediction_score}, "
                f"prediction_decision={prediction_decision}, "
                f"momentum={momentum_direction}"
            ),
        }

    if bias == "buy" and live_negative:
        return {
            "effective_bias": "live_override_neutral",
            "allow_buy": False,
            "confidence_adjustment": -20,
            "reason": (
                "pre-market buy downgraded by live evidence: "
                f"trend={trend_direction}/{trend_strength}, "
                f"setup_action={setup_action}, "
                f"prediction_decision={prediction_decision}, "
                f"momentum={momentum_direction}"
            ),
        }

    if bias == "neutral" and live_strong_positive:
        return {
            "effective_bias": "live_override_buy",
            "allow_buy": True,
            "confidence_adjustment": 5,
            "reason": (
                "neutral pre-market bias upgraded by strong live evidence: "
                f"trend={trend_direction}/{trend_strength}, "
                f"setup={setup_label}, "
                f"prediction_score={prediction_score}, "
                f"momentum={momentum_direction}"
            ),
        }

    return {
        "effective_bias": bias or "neutral",
        "allow_buy": bias != "avoid",
        "confidence_adjustment": 0,
        "reason": "pre-market bias unchanged by live evidence",
    }

def _session_momentum_is_fresh(session_momentum, max_age_minutes=5):
    """Return True when session momentum exists and was refreshed recently."""
    if not session_momentum:
        return False

    updated_at = session_momentum.get("updated_at")
    if not updated_at:
        return False

    try:
        ts = datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S")
        age = datetime.now() - ts
        return age.total_seconds() <= max_age_minutes * 60
    except Exception:
        return False

def _evaluate_session_momentum_gate(session_momentum, prediction_gate, setup_obs, trend):
    """
    Return a session-momentum gate decision for BUY signals.

    Observe/enforce behavior is controlled elsewhere by ENFORCE_SESSION_MOMENTUM_GATE.
    """
    session_momentum = session_momentum or {}
    prediction_gate = prediction_gate or {}
    setup_obs = setup_obs or {}
    trend = trend or {}

    session_label = session_momentum.get("trend_label")
    session_score = int(session_momentum.get("trend_score") or 0)
    prediction_score = int(prediction_gate.get("prediction_score") or 0)
    setup_action = setup_obs.get("setup_policy_action")
    trend_direction = trend.get("direction")
    trend_strength = trend.get("strength")

    session_hard_negative = session_label == "downtrend" or session_score <= -5
    session_soft_negative = session_label == "fading" or session_score <= -2

    # Hard-negative session tape blocks unless the setup is explicitly boosted.
    if session_hard_negative and setup_action != "boost":
        return {
            "would_block": True,
            "severity": "hard_negative",
            "reason": (
                f"session_label={session_label} score={session_score} "
                f"setup_action={setup_action} prediction_score={prediction_score}"
            ),
        }

    # Soft-negative session tape blocks weak/medium setups, but allows very strong
    # prediction or confirmed+boost setups to continue.
    if (
        session_soft_negative
        and prediction_score < 8
        and not (
            trend_direction == "bullish"
            and trend_strength == "confirmed"
            and setup_action == "boost"
        )
    ):
        return {
            "would_block": True,
            "severity": "soft_negative",
            "reason": (
                f"session_label={session_label} score={session_score} "
                f"prediction_score={prediction_score} trend={trend_direction}/{trend_strength} "
                f"setup_action={setup_action}"
            ),
        }

    return {
        "would_block": False,
        "severity": "pass",
        "reason": (
            f"session_label={session_label} score={session_score} "
            f"prediction_score={prediction_score} trend={trend_direction}/{trend_strength} "
            f"setup_action={setup_action}"
        ),
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


def get_momentum(symbol, price, premarket_bias=None):
    try:
        start = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        bars = list(api.get_bars(symbol, '1Min', start=start, feed='iex'))

        if len(bars) < 2:
            return None

        bars = bars[-15:]

        first_close = float(bars[0].c)
        last_close = float(bars[-1].c)

        if first_close <= 0 or last_close <= 0:
            return None

        # Existing short-term momentum, similar to your current behavior
        recent_bars = bars[-5:] if len(bars) >= 5 else bars
        short_first = float(recent_bars[0].c)
        short_last = float(recent_bars[-1].c)

        momentum_5m_pct = (short_last - short_first) / short_first * 100
        momentum_15m_pct = (last_close - first_close) / first_close * 100
        price_vs_bars = (price - last_close) / last_close * 100 if last_close > 0 else 0.0

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
            "momentum_pct": round(momentum_5m_pct, 3),   # preserve existing field name
            "momentum_5m_pct": round(momentum_5m_pct, 3),
            "momentum_15m_pct": round(momentum_15m_pct, 3),
            "price_vs_bars": round(price_vs_bars, 3),
            "bar_count": len(bars),
            "last_close": round(last_close, 4),
            "premarket_bias": premarket_bias,
            "premarket_alignment": alignment,
            "action_hint": action_hint,
        }

    except Exception as e:
        logger.warning(f"get_momentum failed for {symbol}: {e}")
        return None
def _parse_signal_timestamp(data):
    """Best-effort parse of an optional TradingView/client timestamp.

    Supported keys:
      - timestamp
      - time
      - alert_time
      - alert_timestamp

    If no timestamp is present, return None so legacy alerts continue to work.
    """
    raw = (
        data.get("timestamp")
        or data.get("time")
        or data.get("alert_time")
        or data.get("alert_timestamp")
    )
    if not raw:
        return None

    try:
        if isinstance(raw, (int, float)):
            # Treat very large values as milliseconds.
            ts = float(raw) / 1000 if float(raw) > 10_000_000_000 else float(raw)
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        raw_s = str(raw).strip()
        if raw_s.isdigit():
            ts = float(raw_s) / 1000 if len(raw_s) > 10 else float(raw_s)
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        # Accept ISO strings with either "+00:00" or "Z".
        parsed = datetime.fromisoformat(raw_s.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception as e:
        logger.warning(f"Unable to parse signal timestamp {raw!r}: {e}")
        return None


def _is_signal_stale(data):
    """Return (is_stale, age_seconds, reason). Missing timestamps are allowed."""
    ts = _parse_signal_timestamp(data)
    if ts is None:
        return False, None, "no timestamp provided"

    now = datetime.now(timezone.utc)
    age_seconds = (now - ts).total_seconds()

    if age_seconds < -30:
        return True, age_seconds, f"signal timestamp is {abs(age_seconds):.1f}s in the future"

    if age_seconds > SIGNAL_TTL_SECONDS:
        return True, age_seconds, f"signal age {age_seconds:.1f}s exceeds TTL {SIGNAL_TTL_SECONDS}s"

    return False, age_seconds, f"signal age {age_seconds:.1f}s within TTL"

def _make_client_order_id(symbol, action, data):
    """Create a stable Alpaca client_order_id for idempotent broker submission.

    Alpaca client_order_id has a length limit, so keep this compact.
    """
    dedupe_key = str(data.get("_dedupe_key") or "")
    timestamp_hint = str(
        data.get("timestamp")
        or data.get("time")
        or data.get("alert_time")
        or data.get("alert_timestamp")
        or datetime.now(timezone.utc).isoformat()
    )

    raw = json.dumps(
        {
            "symbol": symbol,
            "action": action,
            "price": data.get("price"),
            "source": data.get("source"),
            "dedupe_key": dedupe_key,
            "timestamp": timestamp_hint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"tb-{symbol.lower()}-{action.lower()}-{digest}"

def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_spread_pct(bid, ask):
    bid_f = _safe_float(bid)
    ask_f = _safe_float(ask)

    if bid_f is None or ask_f is None:
        return None
    if bid_f <= 0 or ask_f <= 0:
        return None
    if ask_f <= bid_f:
        return 0.0

    mid = (bid_f + ask_f) / 2.0
    if mid <= 0:
        return None

    return ((ask_f - bid_f) / mid) * 100.0


def _fetch_quote_snapshot(symbol):
    """
    Return a normalized quote snapshot.

    Adapt the body to your existing quote source if needed.
    Expected output keys:
      - bid
      - ask
      - spread_pct
    """
    quote = api.get_latest_quote(symbol)

    bid = getattr(quote, "bid_price", None)
    ask = getattr(quote, "ask_price", None)

    return {
        "bid": _safe_float(bid),
        "ask": _safe_float(ask),
        "spread_pct": _compute_spread_pct(bid, ask),
    }


def _validate_spread_with_retry(
    symbol,
    max_spread_pct=0.10,
    suspect_spread_pct=2.00,
    retry_count=3,
    retry_delay_sec=0.35,
):
    """
    Returns:
      {
        "ok": bool,
        "reason": str | None,
        "bid": float | None,
        "ask": float | None,
        "spread_pct": float | None,
        "attempts": int,
        "suspect_quote": bool,
      }
    """
    last = {
        "bid": None,
        "ask": None,
        "spread_pct": None,
        "attempts": 0,
        "suspect_quote": False,
        "ok": False,
        "reason": "second_look: quote unavailable",
    }

    total_attempts = max(1, retry_count)

    for attempt in range(1, total_attempts + 1):
        snap = _fetch_quote_snapshot(symbol)
        spread_pct = snap["spread_pct"]

        last.update(
            {
                "bid": snap["bid"],
                "ask": snap["ask"],
                "spread_pct": spread_pct,
                "attempts": attempt,
            }
        )

        if spread_pct is None:
            if attempt < total_attempts:
                time.sleep(retry_delay_sec)
                continue
            last["reason"] = "second_look: quote unavailable"
            return last

        if spread_pct <= max_spread_pct:
            last["ok"] = True
            last["reason"] = None
            return last

        if spread_pct > suspect_spread_pct:
            last["suspect_quote"] = True
            if attempt < total_attempts:
                logger.warning(
                    f"Second-look suspect quote for {symbol}: "
                    f"spread {spread_pct:.3f}% on attempt {attempt}/{total_attempts} "
                    f"(bid={snap['bid']:.4f}, ask={snap['ask']:.4f}) — retrying"
                )
                time.sleep(retry_delay_sec)
                continue

            last["reason"] = (
                f"second_look: suspect quote persisted after {attempt} attempts; "
                f"bid/ask spread {spread_pct:.3f}% exceeds suspect threshold "
                f"{suspect_spread_pct:.3f}% "
                f"(bid={snap['bid']:.4f}, ask={snap['ask']:.4f})"
            )
            return last

        last["reason"] = (
            f"second_look: bid/ask spread {spread_pct:.3f}% exceeds max "
            f"{max_spread_pct:.3f}% "
            f"(bid={snap['bid']:.4f}, ask={snap['ask']:.4f})"
        )
        return last

    return last


# Second-look safety thresholds.
# These are env-tunable so paper/live behavior can be adjusted without code edits.
MAX_SIGNAL_PRICE_DRIFT_PCT = float(os.environ.get("MAX_SIGNAL_PRICE_DRIFT_PCT", "0.35"))
MAX_BID_ASK_SPREAD_PCT = float(os.environ.get("MAX_BID_ASK_SPREAD_PCT", "0.10"))

def _pre_order_safety_check(symbol, action, signal_price, account_state):
    """Final broker-adjacent safety check immediately before order placement.

    Returns (ok: bool, reason: str).
    """
    if action != "buy":
        return True, "sell signal bypasses buy-side second-look checks"

    try:
        latest_trade = api.get_latest_trade(symbol)
        latest_price = float(latest_trade.price)
    except Exception as e:
        return False, f"failed to fetch latest trade for second-look check: {e}"

    try:
        signal_price_f = float(signal_price)
    except (TypeError, ValueError):
        return False, f"invalid signal_price for second-look check: {signal_price!r}"

    if signal_price_f <= 0 or latest_price <= 0:
        return False, f"invalid price values signal={signal_price_f} latest={latest_price}"

    drift_pct = abs(latest_price - signal_price_f) / signal_price_f * 100
    if drift_pct > MAX_SIGNAL_PRICE_DRIFT_PCT:
        return (
            False,
            f"latest price drift {drift_pct:.3f}% exceeds max {MAX_SIGNAL_PRICE_DRIFT_PCT:.3f}% "
            f"(signal={signal_price_f:.4f}, latest={latest_price:.4f})",
        )

    # Open-order duplicate protection.
    try:
        open_orders = api.list_orders(status="open", symbols=[symbol])
        if open_orders:
            return False, f"open broker order already exists for {symbol}"
    except Exception as e:
        return False, f"failed to check open orders for {symbol}: {e}"

        # Bid/ask spread check. Fail-open only if quote retrieval is unsupported.
    # For obviously broken quote snapshots, retry a few times before rejecting.
    try:
        spread_check = _validate_spread_with_retry(
            symbol,
            max_spread_pct=MAX_BID_ASK_SPREAD_PCT,
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

            # Buy-side stale-bid exception:
            # If the bid is stale/way below market but the ask is close to the
            # signal and latest trade, allow the order to continue.
            if action == "buy" and ask_f and ask_f > 0:
                ask_vs_signal_pct = abs(ask_f - signal_price_f) / signal_price_f * 100
                ask_vs_latest_pct = abs(ask_f - latest_price) / latest_price * 100

                if (
                    spread_pct is not None
                    and spread_pct > 2.0
                    and ask_vs_signal_pct <= MAX_SIGNAL_PRICE_DRIFT_PCT
                    and ask_vs_latest_pct <= MAX_SIGNAL_PRICE_DRIFT_PCT
                ):
                    logger.warning(
                        f"Second-look stale-bid exception for {symbol} BUY: "
                        f"spread={spread_pct:.3f}% but ask is sane "
                        f"(bid={bid_f if bid_f is not None else 'n/a'}, "
                        f"ask={ask_f:.4f}, "
                        f"signal={signal_price_f:.4f}, latest={latest_price:.4f}, "
                        f"ask_vs_signal={ask_vs_signal_pct:.3f}%, "
                        f"ask_vs_latest={ask_vs_latest_pct:.3f}%)"
                    )
                else:
                    return False, reason
            else:
                return False, reason

    except Exception as e:
        return True, f"spread check unavailable; fail-open: {e}"

        account_state["second_look"] = {
            "latest_price": round(latest_price, 4),
            "price_drift_pct": round(drift_pct, 4),
            "bid": round(spread_check["bid"], 4),
            "ask": round(spread_check["ask"], 4),
            "spread_pct": round(spread_check["spread_pct"], 4),
            "attempts": spread_check["attempts"],
            "suspect_quote": spread_check["suspect_quote"],
        }

    except AttributeError as e:
        logger.warning(f"Second-look quote check unsupported for {symbol}: {e}")
        account_state["second_look"] = {
            "latest_price": round(latest_price, 4),
            "price_drift_pct": round(drift_pct, 4),
            "quote_check": "unsupported",
        }
    except Exception as e:
        return False, f"failed quote/spread second-look check for {symbol}: {e}"

    return True, "second-look checks passed"

def process_signal(data):
    dedupe_key = data.get("_dedupe_key")
    ...
    _load_market_context()
    action = data.get("action", "").lower()
    symbol = data.get("symbol", "")
    price = data.get("price", 0)
    logger.info(f"Processing {action.upper()} signal for {symbol} at {price}")

    account_state = get_mock_account_state()
    account_state["execution_mode"] = EXECUTION_MODE

    def _reject_current_signal(category, reason, level="warning"):
        if level == "error":
            logger.error(f"{category} blocked {symbol} {action.upper()}: {reason}")
        elif level == "info":
            logger.info(f"{category} blocked {symbol} {action.upper()}: {reason}")
        else:
            logger.warning(f"{category} blocked {symbol} {action.upper()}: {reason}")

        log_rejection(
            symbol,
            action,
            category,
            reason,
            price=price,
            account_state=account_state,
        )

        if dedupe_key:
            _mark_webhook_event_status(
                dedupe_key,
                "rejected",
                failure_reason=f"{category}: {reason}",
            )

        return True

    is_stale, age_seconds, stale_reason = _is_signal_stale(data)
    if is_stale:
        logger.warning(
            f"Stale signal blocked for {symbol} {action.upper()}: {stale_reason}"
        )
        log_rejection(
            symbol,
            action,
            "stale_signal",
            stale_reason,
            price=price,
            account_state=account_state,
        )
        return

    if age_seconds is not None:
        account_state["signal_age_seconds"] = round(age_seconds, 2)

    setup_obs = _build_setup_observation(symbol, action, price, account_state)
    account_state["setup_observation"] = setup_obs

    if action == "buy":
        _remember_favorable_setup(symbol, setup_obs)
        recent_favorable_setup = _get_recent_favorable_setup(symbol)
        if recent_favorable_setup:
            account_state["recent_favorable_setup"] = {
                "setup_label": recent_favorable_setup.get("setup_label"),
                "setup_policy_action": recent_favorable_setup.get("setup_policy_action"),
                "age_minutes": recent_favorable_setup.get("age_minutes"),
            }

    if (
        action == "buy"
        and ENFORCE_SETUP_POLICY_BLOCKS
        and setup_obs.get("setup_policy_action") == "block"
    ):
        reason = setup_obs.get("setup_policy_reason") or "setup_policy:block"
        if _reject_current_signal("setup_policy", reason):
            return

    if action == "buy" and is_cash_safe_mode():
        if symbol not in CASH_SAFE_SYMBOLS:
            reason = f"{symbol} not allowed in cash_safe symbols {sorted(CASH_SAFE_SYMBOLS)}"
            logger.warning(f"Cash-safe gate blocked {symbol} BUY: {reason}")
            log_rejection(
                symbol,
                action,
                "cash_safe_symbol",
                reason,
                price=price,
                account_state=account_state,
            )
            return

        open_count = account_state.get("open_position_count", 0)
        if open_count >= CASH_SAFE_MAX_OPEN_POSITIONS:
            reason = (
                f"open_position_count={open_count} >= cash_safe max "
                f"{CASH_SAFE_MAX_OPEN_POSITIONS}"
            )
            logger.warning(f"Cash-safe gate blocked {symbol} BUY: {reason}")
            log_rejection(
                symbol,
                action,
                "cash_safe_position_limit",
                reason,
                price=price,
                account_state=account_state,
            )
            return

        try:
            today = datetime.now().strftime("%Y-%m-%d")
            con = sqlite3.connect(DB_PATH)
            row = con.execute(
                """
                SELECT COUNT(*) FROM trades
                WHERE timestamp LIKE ?
                  AND symbol = ?
                  AND action = 'buy'
                  AND approved = 1
                  AND order_id IS NOT NULL
                """,
                (f"{today}%", symbol),
            ).fetchone()
            con.close()
            buys_today = int(row[0] or 0)
        except Exception as e:
            logger.error(f"Cash-safe daily buy check failed for {symbol}: {e}")
            buys_today = 999

        if buys_today >= CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY:
            reason = (
                f"buys_today={buys_today} >= cash_safe per-symbol daily max "
                f"{CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY}"
            )
            logger.warning(f"Cash-safe gate blocked {symbol} BUY: {reason}")
            log_rejection(
                symbol,
                action,
                "cash_safe_daily_symbol_limit",
                reason,
                price=price,
                account_state=account_state,
            )
            return

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

    # Hard pre-check: market hours
    current_et = now_et()
    if not is_market_hours(current_et):
        reason = f"outside market hours: {current_et.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        if _reject_current_signal("market_hours", reason, level="info"):
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
            if _reject_current_signal("ghost_sell", "no open Alpaca position"):
                return
    existing_position = get_position(symbol)
    if existing_position:
        account_state["current_symbol_position"] = existing_position

    # Sell discipline gate:
    # Prevent normal TradingPilotAI SELL alerts from closing positions too early.
    # Bracket stop-loss/take-profit exits are handled by Alpaca/fill_stream and
    # do not go through this webhook sell path.
    if action == "sell" and existing_position:
        try:
            avg_entry = float(existing_position.get("avg_entry") or 0)
            current_price = float(existing_position.get("current_price") or price or 0)
            qty = float(existing_position.get("qty") or 0)

            # Minimum unrealized profit required before a normal SELL signal
            # is allowed to take profit without stronger bearish confirmation.
            min_profit_to_sell_pct = 0.50

            if avg_entry > 0 and current_price > 0 and qty > 0:
                unrealized_pct = (current_price - avg_entry) / avg_entry * 100

                trend = _trend_table.get(symbol) or {}
                direction = trend.get("direction")
                strength = trend.get("strength")
                consecutive_count = int(trend.get("consecutive_count") or 0)

                confirmed_bearish = (
                    direction == "bearish"
                    and strength in ("developing", "confirmed")
                    and consecutive_count >= 2
                )

                # Do not take tiny profits too early. Let the bracket target
                # or a stronger move develop unless bearish pressure is confirmed.
                if 0 <= unrealized_pct < min_profit_to_sell_pct:
                    if not confirmed_bearish:
                        reason = (
                            f"profit {unrealized_pct:.2f}% below minimum sell threshold "
                            f"{min_profit_to_sell_pct:.2f}% without confirmed bearish pressure "
                            f"(trend={direction}/{strength}, count={consecutive_count})"
                        )
                        if _reject_current_signal("sell_profit_threshold", reason):
                            return

                # Do not close small red positions on weak/noisy sell alerts.
                # Let them work unless bearish pressure is confirmed.
                if -0.75 < unrealized_pct < 0:
                    if not confirmed_bearish:
                        reason = (
                            f"small red position {unrealized_pct:.2f}% without confirmed bearish sell pressure "
                            f"(trend={direction}/{strength}, count={consecutive_count})"
                        )
                        if _reject_current_signal("sell_discipline", reason):
                            return

        except Exception as e:
            logger.warning(f"Sell discipline check failed for {symbol}; fail-open for SELL safety: {e}")

    # Cooldown check: skip if same symbol+action had a successful order within 15 min
    # (Stage B: DB-backed read so all workers see the same cooldown state)
    cooldown_key = (symbol, action)
    last = _read_cooldown(symbol, action)
    if last and (current_et - last).total_seconds() < 15 * 60:
        mins_remaining = int(15 * 60 - (current_et - last).total_seconds()) // 60
        reason = f"{mins_remaining}m remaining (last order {last.strftime('%H:%M')} ET)"
        if _reject_current_signal("cooldown", reason):
            return

    # Sell→buy churn prevention: block buys that follow a recent sell on the same symbol
    # (Stage B: DB-backed read so all workers see the same recent-sell state)
    if action == "buy":
        last_sell = _read_recent_sell(symbol)
        if last_sell:
            last_sell_time, last_sell_price = last_sell
            elapsed_s = (current_et - last_sell_time).total_seconds()
            if elapsed_s < 30 * 60:
                mins_remaining = int(30 * 60 - elapsed_s) // 60
                reason = f"sold at ${last_sell_price:.2f}, {mins_remaining}m remaining in 30-min window"
                if _reject_current_signal("churn_window", reason):
                    return
            if last_sell_price > 0:
                price_diff_pct = abs(price - last_sell_price) / last_sell_price * 100
                if price_diff_pct < 0.5:
                    reason = f"signal ${price:.2f} within {price_diff_pct:.2f}% of last sell ${last_sell_price:.2f}"
                    if _reject_current_signal("churn_price", reason):
                        return

    # Daily symbol buy limit: prevent repeated same-symbol accumulation from alert storms.
    # Allows initial entry plus one add by default.
    if action == "buy":
        buys_today = _successful_buys_today(symbol)
        if buys_today >= MAX_BUYS_PER_SYMBOL_PER_DAY:
            reason = f"successful_buys_today={buys_today} >= limit={MAX_BUYS_PER_SYMBOL_PER_DAY}"
            if _reject_current_signal("daily_symbol_buy_limit", reason):
                return

    # Hard pre-check: 4% per-symbol exposure cap (buy signals only)
    if action == "buy" and existing_position:
        balance = account_state.get("balance", 0)
        position_value = existing_position["qty"] * existing_position["current_price"]
        if balance > 0:
            exposure_pct = position_value / balance * 100
            if exposure_pct >= 4.0:
                reason = f"position ${position_value:.2f} = {exposure_pct:.2f}% of balance (limit 4.0%)"
                if _reject_current_signal("exposure_cap", reason):
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
                if _reject_current_signal("correlation_cap", reason):
                    return

        if cluster_checks:
            account_state["correlation_exposure"] = cluster_checks

    # Macro-risk gate: regime-aware risk control before Claude
    macro_risk = get_macro_risk(Path(__file__).parent)
    account_state["macro_risk"] = macro_risk

    if action == "buy":
        if macro_risk.get("block_new_buys"):
            reason = macro_risk.get("reason", "macro regime blocks new buys")
            if _reject_current_signal("macro_risk", reason):
                return

        max_new_positions = macro_risk.get("max_new_positions", 8)
        open_count = account_state.get("open_position_count", 0)
        if open_count >= max_new_positions:
            reason = f"open_position_count={open_count} >= macro max_new_positions={max_new_positions}"
            if _reject_current_signal("macro_position_limit", reason):
                return

    # Trend confirmation gate: require confirmed indicator-state transitions before allowing signals through.
    if action == "buy":
        trend = _trend_table.get(symbol) or {}
        direction = trend.get("direction")
        strength = trend.get("strength")
        consecutive_count = int(trend.get("consecutive_count") or 0)
        last_signal = trend.get("last_signal")

        adaptive_confirmation = _required_buy_confirmations(symbol, account_state)
        required_buy_confirmations = int(
            adaptive_confirmation.get("required_buy_confirmations") or 3
        )
        account_state["adaptive_buy_confirmation"] = adaptive_confirmation

        if direction != "bullish" or last_signal != "buy":
            reason = (
                f"direction={direction} "
                f"last_signal={last_signal} "
                f"required={required_buy_confirmations}"
            )
            if _reject_current_signal("trend_confirmation", reason):
                return

        fast_lane_buy_flip = is_fast_lane_buy_flip(
            trend,
            required_buy_confirmations=required_buy_confirmations,
        )
        account_state["fast_lane_buy_flip"] = fast_lane_buy_flip

        logger.info(
            f"Trend confirmation BUY for {symbol}: "
            f"required={required_buy_confirmations} "
            f"count={consecutive_count} "
            f"direction={direction} "
            f"strength={strength} "
            f"last_signal={last_signal} "
            f"flip_event={trend.get('flip_event')} "
            f"fast_lane_buy_flip={fast_lane_buy_flip} "
            f"adaptive_reason={adaptive_confirmation.get('reason')}"
        )

        if not fast_lane_buy_flip and consecutive_count < required_buy_confirmations:
            reason = (
                f"consecutive_buy_count={consecutive_count} "
                f"< required={required_buy_confirmations} "
                f"strength={strength} "
                f"flip_event={trend.get('flip_event')}"
            )
            if _reject_current_signal("trend_confirmation", reason):
                return

    if action == "sell":
        trend = _trend_table.get(symbol) or {}
        direction = trend.get("direction")
        strength = trend.get("strength")
        consecutive_count = int(trend.get("consecutive_count") or 0)
        last_signal = trend.get("last_signal")

        sell_confirmation = _required_sell_confirmations(symbol, account_state)
        required_sell_confirmations = int(
            sell_confirmation.get("required_sell_confirmations") or 2
        )
        account_state["sell_confirmation"] = sell_confirmation

        if direction != "bearish" or last_signal != "sell":
            reason = (
                f"direction={direction} "
                f"last_signal={last_signal} "
                f"required={required_sell_confirmations}"
            )
            if _reject_current_signal("trend_confirmation", reason):
                return

        fast_lane_sell_flip = is_fast_lane_sell_flip(
            trend,
            required_sell_confirmations=required_sell_confirmations,
        )
        account_state["fast_lane_sell_flip"] = fast_lane_sell_flip

        logger.info(
            f"Trend confirmation SELL for {symbol}: "
            f"required={required_sell_confirmations} "
            f"count={consecutive_count} "
            f"direction={direction} "
            f"strength={strength} "
            f"last_signal={last_signal} "
            f"flip_event={trend.get('flip_event')} "
            f"fast_lane_sell_flip={fast_lane_sell_flip} "
            f"sell_reason={sell_confirmation.get('reason')}"
        )

        if not fast_lane_sell_flip and consecutive_count < required_sell_confirmations:
            reason = (
                f"consecutive_sell_count={consecutive_count} "
                f"< required={required_sell_confirmations} "
                f"strength={strength} "
                f"flip_event={trend.get('flip_event')}"
            )
            if _reject_current_signal("trend_confirmation", reason):
                return

    # Fundamental score gate: block buys when manual/pre-market research flags weak fundamentals
    bias_entry = _market_bias.get(symbol) or {}

    if action == "buy":
        if bias_entry:
            fundamental_score = bias_entry.get("fundamental_score")
            if fundamental_score in ("bearish", "strong_bearish"):
                reason = f"fundamental_score={fundamental_score}"
                if _reject_current_signal("fundamental_score", reason):
                    return

        # Market-bias context injection.
        #
        # Do not block on market_bias here. Live evidence from momentum,
        # prediction scoring, setup policy, and indicator state is evaluated
        # below before the effective intraday bias is enforced.
        if action == "buy" and bias_entry:
            bias = bias_entry.get("bias")
            account_state["market_bias_original"] = bias
            account_state["market_bias"] = bias
            account_state["avoid_type"] = bias_entry.get("avoid_type")
            account_state["soft_avoid_reason"] = bias_entry.get("reason", "")

            if bias_entry.get("fundamental_score"):
                account_state["fundamental_score"] = bias_entry["fundamental_score"]
            if bias_entry.get("risk_level"):
                account_state["risk_level"] = bias_entry["risk_level"]
            if bias_entry.get("entry_quality"):
                account_state["entry_quality"] = bias_entry["entry_quality"]

        # Chase prevention gate
        if action == "buy":
            if bias_entry:
                eq = bias_entry.get("entry_quality")
                if eq in ("do_not_chase", "avoid_chasing"):
                    reason = f"entry_quality={eq} risk_level={bias_entry.get('risk_level') or '-'}"
                    if _reject_current_signal("chase_prevention", reason):
                        return

    # Session-aware momentum context, observe-only.
    # This reads the latest state produced by session_momentum.py.
    # It does not fetch bars or block trading here.
    try:
        session_momentum = get_latest_session_momentum(symbol)

        if session_momentum and _session_momentum_is_fresh(session_momentum):
            account_state["session_momentum"] = session_momentum
            logger.info(
                f"Session momentum for {symbol}: "
                f"label={session_momentum.get('trend_label')} "
                f"score={session_momentum.get('trend_score')} "
                f"session_return={session_momentum.get('session_return_pct')} "
                f"5m={session_momentum.get('momentum_5m_pct')} "
                f"15m={session_momentum.get('momentum_15m_pct')} "
                f"30m={session_momentum.get('momentum_30m_pct')} "
                f"vwap_dist={session_momentum.get('distance_from_vwap_pct')}"
            )
        else:
            account_state["session_momentum"] = {
                "trend_label": "insufficient_data",
                "trend_score": 0,
                "reason": "missing or stale session momentum",
            }
            logger.info(f"Session momentum unavailable/stale for {symbol}; using insufficient_data")
    except Exception as e:
        account_state["session_momentum"] = {
            "trend_label": "insufficient_data",
            "trend_score": 0,
            "reason": f"session momentum read error: {e}",
        }
        logger.warning(f"Session momentum unavailable for {symbol}: {e}")

    # Momentum check (buy signals only, fail-open — never blocks trading)
    alignment = None
    action_hint = None

    if action == "buy":
        premarket_bias = bias_entry.get("bias")
        momentum = get_momentum(symbol, price, premarket_bias=premarket_bias)
        if momentum:
            account_state["momentum"] = momentum

            alignment = momentum.get("premarket_alignment")
            action_hint = momentum.get("action_hint")

            if alignment == "contradicted":
                account_state["signal_confidence_hint"] = "low"
                logger.warning(
                    f"Pre-market alignment contradicted for {symbol} BUY: "
                    f"bias={momentum.get('premarket_bias')} "
                    f"5m={momentum.get('momentum_5m_pct')}% "
                    f"15m={momentum.get('momentum_15m_pct')}% "
                    f"hint={action_hint} — confidence hint set to low"
                )

            elif alignment == "confirmed":
                account_state["signal_confidence_hint"] = "high"
                logger.info(
                    f"Pre-market alignment confirmed for {symbol} BUY: "
                    f"bias={momentum.get('premarket_bias')} "
                    f"5m={momentum.get('momentum_5m_pct')}% "
                    f"15m={momentum.get('momentum_15m_pct')}% "
                    f"hint={action_hint} — confidence hint set to high"
                )

            elif momentum["direction"] == "falling" and momentum["momentum_pct"] < -0.15:
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
            reason = (
                f"existing position with risk_level={risk_level} "
                f"and momentum_direction={momentum_direction or 'unknown'}"
            )
            if _reject_current_signal("addon_momentum_gate", reason):
                return

    # Prediction gate: score buy quality after macro, bias, setup, and momentum are populated.
    if action == "buy":
        trend = _trend_table.get(symbol) or {}
        bias_entry = _market_bias.get(symbol) or {}
        setup_obs = account_state.get("setup_observation") or {}
        momentum = account_state.get("momentum") or {}
        recent_favorable_setup = account_state.get("recent_favorable_setup")

        prediction_gate = evaluate_prediction_gate(
            trend_direction=trend.get("direction"),
            trend_strength=trend.get("strength"),
            market_bias=bias_entry.get("bias"),
            setup_label=setup_obs.get("setup_label"),
            setup_policy_action=setup_obs.get("setup_policy_action"),
            momentum_direction=momentum.get("direction"),
            momentum_pct=momentum.get("momentum_pct"),
            consecutive_buy_count=trend.get("consecutive_count") or 0,
            recent_favorable_setup=recent_favorable_setup,
        )

        account_state["prediction_gate"] = prediction_gate

        logger.info(
            f"Prediction gate for {symbol} BUY: "
            f"score={prediction_gate.get('prediction_score')} "
            f"decision={prediction_gate.get('prediction_decision')} "
            f"reason={prediction_gate.get('prediction_reason')}"
        )

        prediction_decision = prediction_gate.get("prediction_decision")

        bias_override = _live_bias_override(
            symbol=symbol,
            bias_entry=bias_entry,
            trend=trend,
            setup_obs=setup_obs,
            prediction_gate=prediction_gate,
            momentum=momentum,
        )

        account_state["market_bias_effective"] = bias_override.get("effective_bias")
        account_state["market_bias_override_reason"] = bias_override.get("reason")

        effective_bias = bias_override.get("effective_bias")
        allow_buy_from_bias = bool(bias_override.get("allow_buy"))

        if effective_bias == "avoid_hard":
            reason = (
                f"effective_bias={effective_bias} "
                f"confidence={bias_entry.get('confidence','')} "
                f"reason={bias_override.get('reason')}; "
                f"context_reason={bias_entry.get('reason','')}"
            )
            if _reject_current_signal("market_bias_avoid", reason):
                return

        if effective_bias == "avoid_soft" and not allow_buy_from_bias:
            reason = (
                f"effective_bias={effective_bias}; "
                f"{bias_override.get('reason')}; "
                f"context_reason={bias_entry.get('reason','')}"
            )
            if _reject_current_signal("soft_avoid_prediction_gate", reason):
                return

        if effective_bias == "live_override_neutral" and not allow_buy_from_bias:
            reason = (
                f"effective_bias={effective_bias}; "
                f"{bias_override.get('reason')}; "
                f"context_reason={bias_entry.get('reason','')}"
            )
            if _reject_current_signal("live_bias_downgrade", reason):
                return

        if effective_bias == "live_override_buy":
            logger.info(
                f"Live evidence overrode pre-market bias for {symbol} BUY: "
                f"{bias_override.get('reason')}"
            )

        should_block_prediction = (
            (ENFORCE_PREDICTION_BLOCKS and prediction_decision == "block")
            or (
                ENFORCE_PREDICTION_WATCH_IN_CASH
                and is_cash_mode()
                and prediction_decision == "watch"
            )
        )

        if should_block_prediction:
            reason = (
                f"mode={EXECUTION_MODE} "
                f"score={prediction_gate.get('prediction_score')} "
                f"decision={prediction_decision} "
                f"reason={prediction_gate.get('prediction_reason')}"
            )
            if _reject_current_signal("prediction_gate", reason):
                return

        session_gate = _evaluate_session_momentum_gate(
            session_momentum=account_state.get("session_momentum") or {},
            prediction_gate=prediction_gate,
            setup_obs=setup_obs,
            trend=trend,
        )
        account_state["session_momentum_gate"] = session_gate

        if session_gate.get("would_block"):
            reason = session_gate.get("reason", "session momentum gate")
            if ENFORCE_SESSION_MOMENTUM_GATE:
                if _reject_current_signal("session_momentum_gate", reason):
                    return
            else:
                logger.info(
                    f"Session momentum gate observe-only for {symbol} BUY: "
                    f"{session_gate.get('severity')} {reason}"
                )

    account_state["trend_table"] = _trend_table

    final_setup_obs = account_state.get("setup_observation") or {}
    final_prediction_gate = account_state.get("prediction_gate") or {}
    final_session_momentum = account_state.get("session_momentum") or {}
    final_session_gate = account_state.get("session_momentum_gate") or {}

    logger.info(
        f"Decision context for {symbol} {action.upper()}: "
        f"setup={final_setup_obs.get('setup_label')}/"
        f"{final_setup_obs.get('setup_policy_action')} "
        f"prediction={final_prediction_gate.get('prediction_score')}/"
        f"{final_prediction_gate.get('prediction_decision')} "
        f"session={final_session_momentum.get('trend_label')}/"
        f"{final_session_momentum.get('trend_score')} "
        f"session_gate={final_session_gate.get('severity')}/"
        f"{final_session_gate.get('would_block')} "
        f"effective_bias={account_state.get('market_bias_effective')}"
    )

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
    if action == "buy" and is_cash_safe_mode() and decision.get("confidence") != "high":
        logger.warning(
            f"Cash-safe confidence gate rejected {symbol} BUY: "
            f"confidence={decision.get('confidence')}"
        )
        log_rejection(
            symbol,
            action,
            "cash_safe_confidence",
            f"cash_safe requires confidence=high; got {decision.get('confidence')} "
            f"(reason: {decision.get('reason', '')})",
            price=price,
            account_state=account_state,
        )
        return

    if action == "buy" and decision.get("confidence") == "low":
        logger.warning(f"Low confidence BUY rejected for {symbol}: skipping order placement")
        log_rejection(
            symbol, action, "confidence_gate",
            f"Claude returned confidence=low (reason: {decision.get('reason', '')})",
            price=price, account_state=account_state,
        )
        return

    if decision.get("approved"):
        try:
            approved_reason = decision.get("reason")
            logger.info(f"APPROVED: {symbol} {action.upper()} - {approved_reason}")

            risk_multiplier = float(account_state.get("macro_risk", {}).get("risk_multiplier", 1.0))
            adjusted_position_size_pct = decision.get("position_size_pct", 1.0) * risk_multiplier

            logger.info(
                f"ORDER PATH START: {symbol} {action.upper()} "
                f"exec_mode={EXECUTION_MODE} "
                f"position_size_pct={decision.get('position_size_pct')} "
                f"risk_multiplier={risk_multiplier} "
                f"adjusted_position_size_pct={adjusted_position_size_pct:.3f}"
            )

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
                logger.info(f"SECOND LOOK START: {symbol} {action.upper()}")
                ok, second_look_reason = _pre_order_safety_check(
                    symbol=symbol,
                    action=action,
                    signal_price=price,
                    account_state=account_state,
                )
                logger.info(
                    f"SECOND LOOK RESULT: {symbol} {action.upper()} "
                    f"ok={ok} reason={second_look_reason}"
                )

                if not ok:
                    logger.warning(
                        f"Second-look safety check blocked {symbol} {action.upper()}: "
                        f"{second_look_reason}"
                    )
                    log_rejection(
                        symbol,
                        action,
                        "second_look",
                        second_look_reason,
                        price=price,
                        account_state=account_state,
                    )
                    if dedupe_key:
                        _mark_webhook_event_status(
                            dedupe_key,
                            "rejected",
                            failure_reason=f"second_look: {second_look_reason}",
                        )
                    return

                client_order_id = _make_client_order_id(symbol, action, data)
                logger.info(
                    f"BROKER SUBMIT START: {symbol} {action.upper()} "
                    f"client_order_id={client_order_id}"
                )

                order_result = place_order(
                    symbol=symbol,
                    action=action,
                    position_size_pct=adjusted_position_size_pct,
                    stop_loss_pct=decision.get("stop_loss_pct", 0.5),
                    take_profit_pct=decision.get("take_profit_pct", 1.5),
                    risk_level=account_state.get("risk_level"),
                    client_order_id=client_order_id,
                )

                logger.info(
                    f"BROKER SUBMIT RESULT: {symbol} {action.upper()} "
                    f"order_result={order_result}"
                )

            if order_result:
                if EXECUTION_MODE == "dry_run":
                    logger.info(f"DRY RUN ORDER RECORDED: {order_result}")
                else:
                    logger.info(f"ORDER PLACED: {order_result}")
                    _last_order[cooldown_key] = current_et
                    _write_cooldown(symbol, action, current_et)
                    if action == "sell":
                        _last_sell[symbol] = (current_et, price)
                        _write_recent_sell(symbol, current_et, price)
            else:
                logger.error(f"Order placement failed for {symbol}")
                if dedupe_key:
                    _mark_webhook_event_status(
                        dedupe_key,
                        "submit_failed",
                        failure_reason="broker returned no order_result",
                    )

        except Exception as e:
            logger.exception(
                f"APPROVED ORDER PATH CRASHED for {symbol} {action.upper()}: {e}"
            )
            log_rejection(
                symbol,
                action,
                "order_path_exception",
                str(e),
                price=price,
                account_state=account_state,
            )
            if dedupe_key:
                _mark_webhook_event_status(
                    dedupe_key,
                    "error",
                    failure_reason=f"order_path_exception: {e}",
                )
            return

    else:
        rejected_reason = decision.get("reason")
        logger.info(f"REJECTED: {symbol} {action.upper()} - {rejected_reason}")
    log_trade(data, decision, order_result, account_state=account_state)
    if dedupe_key:
        _mark_webhook_event_status(dedupe_key, "processed")

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

    dedupe_key = _make_dedupe_key(data)
    is_new_event = _record_webhook_event(dedupe_key, data)

    if not is_new_event:
        logger.warning(
            f"Duplicate webhook ignored: symbol={symbol} action={action} "
            f"price={price} dedupe_key={dedupe_key[:24]}..."
        )
        return jsonify({
            "status": "duplicate_ignored",
            "symbol": symbol,
            "action": action,
            "price": price,
            "timestamp": datetime.now().isoformat(),
        }), 200

    data["_dedupe_key"] = dedupe_key
        
    try:
        data["_dedupe_key"] = dedupe_key

        _mark_webhook_event_status(dedupe_key, "queued")
        _signal_executor.submit(process_signal, data)
    except Exception as e:
        logger.error(f"Failed to submit signal to executor for {symbol} {action.upper()}: {e}")
        _mark_webhook_event_status(
            dedupe_key,
            "error",
            failure_reason=f"failed to queue signal: {e}",
        )
        return jsonify({
            "status": "error",
            "reason": "failed to queue signal",
            "symbol": symbol,
            "action": action,
            "price": price,
            "timestamp": datetime.now().isoformat(),
        }), 503

    return jsonify({
        "status": "received",
        "queued": True,
        "symbol": symbol,
        "action": action,
        "price": price,
        "timestamp": datetime.now().isoformat(),
    }), 200

@app.route("/health", methods=["GET"])
def health():
    account = get_account()
    return jsonify({
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "account": account
    }), 200

def _market_session():
    return market_session()

def _session_momentum_summary():
    """Return counts of latest session momentum labels across all tracked symbols."""
    try:
        with get_connection(DB_PATH) as con:
            rows = con.execute(
                """
                SELECT trend_label, COUNT(*) AS n
                FROM session_momentum
                GROUP BY trend_label
                ORDER BY n DESC
                """
            ).fetchall()

        return {
            (r["trend_label"] or "unknown"): r["n"]
            for r in rows
        }
    except Exception as e:
        logger.warning(f"session momentum summary unavailable: {e}")
        return {}


def _session_momentum_snapshot(limit=40):
    """Return latest session momentum rows for status/debug visibility."""
    try:
        with get_connection(DB_PATH) as con:
            rows = con.execute(
                """
                SELECT symbol, updated_at, trend_label, trend_score,
                       session_return_pct, momentum_5m_pct,
                       momentum_15m_pct, momentum_30m_pct,
                       distance_from_vwap_pct, reason
                FROM session_momentum
                ORDER BY symbol
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"session momentum snapshot unavailable: {e}")
        return []

def _latest_session_momentum_for_symbol(symbol):
    """Return latest session momentum for one symbol."""
    try:
        row = get_latest_session_momentum(symbol)
        return dict(row) if row else None
    except Exception as e:
        logger.warning(f"session momentum unavailable for {symbol}: {e}")
        return None

@app.route("/status", methods=["GET"])
def status():
    result = {
        "timestamp": datetime.now().isoformat(),
        "execution_mode": EXECUTION_MODE,
        "runtime_config": public_runtime_config(),
    }
    result["session_momentum_gate_enabled"] = ENFORCE_SESSION_MOMENTUM_GATE
    result["session_momentum_summary"] = _session_momentum_summary()
    result["session_momentum"] = _session_momentum_snapshot()
    
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
                    "session_momentum": _latest_session_momentum_for_symbol(p.symbol),
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
        now_et_value = now_et()
        market_hours_open = is_market_hours(now_et_value)

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
                    elapsed = (now_et_value - ts).total_seconds()
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
                    elapsed = (now_et_value - ts).total_seconds()
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
        result["trend_table_summary"] = {}
        for sym in sorted(APPROVED_SYMBOLS):
            t = _trend_table.get(sym)
            if not t:
                result["trend_table_summary"][sym] = None
                continue

            buy_confirmation = _required_buy_confirmations(sym, result.get("account") or {})
            sell_confirmation = _required_sell_confirmations(sym, result.get("account") or {})

            result["trend_table_summary"][sym] = {
                "direction": t.get("direction"),
                "strength": t.get("strength"),
                "consecutive_count": t.get("consecutive_count"),
                "last_signal": t.get("last_signal"),
                "flip_event": t.get("flip_event"),
                "required_buy_confirmations": buy_confirmation.get("required_buy_confirmations"),
                "required_sell_confirmations": sell_confirmation.get("required_sell_confirmations"),
                "fast_lane_buy_flip": is_fast_lane_buy_flip(
                    t,
                    required_buy_confirmations=buy_confirmation.get("required_buy_confirmations") or 3,
                ),
                "fast_lane_sell_flip": is_fast_lane_sell_flip(
                    t,
                    required_sell_confirmations=sell_confirmation.get("required_sell_confirmations") or 2,
                ),
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
            now_et_value = now_et()
            market_hours_open = is_market_hours(now_et_value)
            for (sym, _action), ts in _last_order.items():
                if sym == symbol and (now_et_value - ts).total_seconds() < 15 * 60:
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

    now_et_value = now_et()
    market_hours_open = is_market_hours(now_et_value)
    
    result = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "now_et": now_et_value.strftime("%Y-%m-%d %H:%M:%S %Z"),
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

    # Trend snapshot for all approved symbols
    try:
        result["trend_table_summary"] = {}
        for sym in sorted(APPROVED_SYMBOLS):
            t = _trend_table.get(sym)
            if not t:
                result["trend_table_summary"][sym] = None
                continue

            buy_confirmation = _required_buy_confirmations(sym, result.get("account") or {})
            sell_confirmation = _required_sell_confirmations(sym, result.get("account") or {})

            result["trend_table_summary"][sym] = {
                "direction": t.get("direction"),
                "strength": t.get("strength"),
                "consecutive_count": t.get("consecutive_count"),
                "last_signal": t.get("last_signal"),
                "flip_event": t.get("flip_event"),
                "required_buy_confirmations": buy_confirmation.get("required_buy_confirmations"),
                "required_sell_confirmations": sell_confirmation.get("required_sell_confirmations"),
                "fast_lane_buy_flip": is_fast_lane_buy_flip(
                    t,
                    required_buy_confirmations=buy_confirmation.get("required_buy_confirmations") or 3,
                ),
                "fast_lane_sell_flip": is_fast_lane_sell_flip(
                    t,
                    required_sell_confirmations=sell_confirmation.get("required_sell_confirmations") or 2,
                ),
            }
    except Exception as e:
        logger.error(f"/status trend_table_summary error: {e}")

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
                elapsed = (now_et_value - last).total_seconds()
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
            elapsed = (now_et_value - ts).total_seconds()
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
    prediction_gate = (state or {}).get("prediction_gate") or {}

    if prediction_gate.get("prediction_decision") == "block":
        buy_blocks.append(
            f"prediction_gate:{prediction_gate.get('prediction_score')}:{prediction_gate.get('prediction_reason')}"
    )
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
