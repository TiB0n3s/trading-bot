import os
import sys
import json
import logging
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytz
import time
from setup_policy import evaluate_setup_policy
from pathlib import Path
from live_features import build_snapshot
from flask import Flask, abort
from api.debug_routes import DebugRouteDeps, create_debug_blueprint
from api.request_services import RequestAuthService, ResponseFactory, WebhookPayloadParser
from api.status_routes import StatusRouteDeps, create_status_blueprint
from api.webhook_routes import WebhookRouteDeps, create_webhook_blueprint
from services.container import ApplicationContainer
from services.status_service import build_status_payload
from services.positions_service import build_positions_payload
from services.debug_symbol_service import build_debug_symbol_payload
from services import dedupe_service
from services.observability import metrics_snapshot
from services.policies import entry_policy, execution_policy, sizing_policy
from services.policy_controls import public_policy_control_config
from services.approval_service import (
    ApprovalDecision,
    decision_policy_rejection,
    evaluate_approval_decision,
    live_bias_rejection,
    opportunity_score_rejection,
    prediction_gate_rejection,
    session_momentum_rejection,
    setup_policy_rejection,
    strategy_memory_rejection,
    trend_confirmation_rejection,
)
from services.context_builder import (
    ContextAssemblyDeps,
    build_legacy_signal_context,
)
from services.preflight_service import (
    PreflightDeps,
    PreflightService,
    normalize_signal_identity,
)
from services.sizing_service import apply_final_sizing, apply_size_cap, build_conviction_stack
from services.execution_service import execute_order
from services.signal_pipeline import SignalPipelineDeps
from services.signal_models import SignalRuntimeState
from services import trend_context_service
from services import trade_audit_service
from services.setup_context_service import (
    SetupContextDeps,
    is_degraded_setup,
    is_favorable_setup_label,
    is_unrecognized_setup_label,
)
from repositories import context_repo, cooldown_repo, trades_repo
from indicator_state import (
    is_fast_lane_buy_flip,
    is_fast_lane_sell_flip,
)
from session_momentum import (
    init_session_momentum_table,
    get_latest_session_momentum,
)
from decision_engine import evaluate_signal, get_mock_account_state
from opportunity_score import score_buy_opportunity
from macro_risk import get_macro_risk
from setup_classifier import classify_setup
from strategy_memory import memory_for_signal
from decision_context import build_intelligence_context
from decision_policy import evaluate_decision_policy
from intelligence_snapshot import get_intelligence_snapshot
from position_intelligence import get_position_intelligence
from bot_events import log_event
from rolling_context import rolling_summary, rolling_symbol_context
from prior_session_context import prior_session_context
from decision_thresholds import PREDICTION_GATE_THRESHOLDS
from strategy.strategy_engine import evaluate_strategy_observe_only
from risk.account_risk import account_risk_snapshot
from risk.live_guards import live_guard_policy, live_order_allowed
from risk.macro_policy import policy_from_market_context
from data_layer.ledger import ledger_summary
from alerts import alert_config_public
from policy_artifacts import policy_artifact_status
from prediction_cache import (
    get_cached_prediction,
    prediction_cache_status,
    start_prediction_cache_loader,
)
from exceptions import ValidationError
from rejection_categories import format_rejection_reason
from runtime_config import (
    EXECUTION_MODE,
    LIVE_TRADING_ENABLED,
    CASH_SAFE_SYMBOLS,
    CASH_SAFE_MAX_OPEN_POSITIONS,
    CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY,
    MAX_LIVE_ORDER_DOLLARS,
    CASH_SAFE_MAX_ORDER_DOLLARS,
    DECISION_POLICY_LIVE_BLOCK,
    DECISION_POLICY_LIVE_SIZE_DOWN,
    decision_policy_live_authority_enabled,
    public_decision_policy_config,
    is_cash_mode,
    is_cash_safe_mode,
    public_runtime_config,
)
from symbols_config import (
    APPROVED_SYMBOLS,
    CORRELATION_CLUSTERS,
    CLUSTER_EXPOSURE_LIMITS,
    PRICE_RANGES,
    SYMBOL_MAX_SPREAD_PCT,
    IEX_THIN_SYMBOLS,
)
from market_time import now_et, is_market_hours, market_session, expected_market_context_date
from db import init_db_performance_indexes
from db import (
    DB_PATH,
    ensure_recent_favorable_setups_table,
    upsert_recent_favorable_setup,
    get_recent_favorable_setup,
    prune_recent_favorable_setups,
)
from strategy_constants import (
    MARKET_OPEN_MINUTES,
    MARKET_CLOSE_MINUTES,
    DAILY_LOSS_LIMIT_PCT,
    MAX_BUYS_PER_SYMBOL_PER_DAY,
    MAX_OPEN_POSITIONS,
    WEBHOOK_DEDUPE_SECONDS,
    SYMBOL_MARKET_ALIGNMENT,
    ADAPTIVE_BUY_CONFIRMATION_ENABLED,
)
IS_PAPER_MODE = EXECUTION_MODE == "paper"

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)
ET = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)

app = Flask(__name__)
container = ApplicationContainer.create_default(
    logger=logger,
    signal_executor_factory=lambda: _get_signal_executor(),
)

# Compatibility aliases while legacy orchestration is still being reduced.
broker_service = container.broker_service
market_data_service = container.market_data_service
tape_service = container.tape_service

DB_PATH = Path(__file__).parent / "trades.db"
_START_TIME = datetime.now(timezone.utc)
ENFORCE_SETUP_POLICY_BLOCKS = True

PREDICTION_GATE_MODE = os.getenv("PREDICTION_GATE_MODE", "warn").strip().lower()
PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE = int(os.getenv("PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE", "20"))

INTRA_SESSION_TAPE_DEGRADATION_ENABLED = os.getenv(
    "INTRA_SESSION_TAPE_DEGRADATION_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET = int(
    os.getenv("INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET", "12")
)
INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE = float(
    os.getenv("INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE", "55")
)

ONE_BAR_CONFIRMATION_HOLD_ENABLED = os.getenv(
    "ONE_BAR_CONFIRMATION_HOLD_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT = float(
    os.getenv("ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT", "0.25")
)
ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS = int(
    os.getenv("ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS", "75")
)

# Tape exception for the neutral-bias confidence gate.
# When true, accelerating momentum + elevated/surge volume + clean_momentum tape
# overrides a stale neutral pre-market classification and allows medium confidence through.
TAPE_EXCEPTION_ENABLED = os.getenv(
    "TAPE_EXCEPTION_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")

# Open-momentum fast lane for the trend confirmation gate.
# When true, surge volume + accelerating momentum within the first 60 minutes
# bypasses the consecutive-count requirement on buy-bias symbols.
# gap_up_chase_risk exclusion prevents firing on extended gap-up chases.
OPEN_MOMENTUM_FAST_LANE_ENABLED = os.getenv(
    "OPEN_MOMENTUM_FAST_LANE_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")

# Minimum market_value (USD) for a position to count toward the macro position cap.
# Positions below this floor are residual/micro lots and should not consume a slot.
MACRO_POSITION_COUNT_FLOOR = float(
    os.getenv("MACRO_POSITION_COUNT_FLOOR", "500.0")
)

if PREDICTION_GATE_MODE not in ("off", "warn", "soft", "hard"):
    logger.warning(
        f"Invalid PREDICTION_GATE_MODE={PREDICTION_GATE_MODE!r}; defaulting to warn"
    )
    PREDICTION_GATE_MODE = "warn"

# Prediction promotion ladder:
# - warn/off/soft: do not hard-reject; keep telemetry and reports active
# - hard: block prediction_decision=block and block watch in cash mode only
# Hard mode requires enough labeled paper-session outcomes and operator review.
ENFORCE_PREDICTION_BLOCKS = PREDICTION_GATE_MODE == "hard"
ENFORCE_PREDICTION_WATCH_IN_CASH = PREDICTION_GATE_MODE == "hard"

STRATEGY_ENGINE_MODE = os.getenv("STRATEGY_ENGINE_MODE", "observe").strip().lower()
if STRATEGY_ENGINE_MODE not in ("off", "observe"):
    logger.warning(
        f"Invalid STRATEGY_ENGINE_MODE={STRATEGY_ENGINE_MODE!r}; defaulting to observe"
    )
    STRATEGY_ENGINE_MODE = "observe"

RISK_POLICY_MODE = os.getenv("RISK_POLICY_MODE", "compare").strip().lower()
if RISK_POLICY_MODE not in ("off", "compare"):
    logger.warning(
        f"Invalid RISK_POLICY_MODE={RISK_POLICY_MODE!r}; defaulting to compare"
    )
    RISK_POLICY_MODE = "compare"

ENFORCE_SESSION_MOMENTUM_GATE = os.getenv(
    "ENFORCE_SESSION_MOMENTUM_GATE",
    "false"
).strip().lower() in ("1", "true", "yes", "on")

ENFORCE_ADAPTIVE_CHURN_REENTRY = os.getenv(
    "ENFORCE_ADAPTIVE_CHURN_REENTRY",
    "true"
).strip().lower() in ("1", "true", "yes", "on")
SIGNAL_WORKER_COUNT = int(os.environ.get("SIGNAL_WORKER_COUNT", "3"))
RECENT_FAVORABLE_SETUP_TTL_MINUTES = 15
_signal_executor = None
_STARTUP_TASKS_RAN = False


def _get_signal_executor() -> ThreadPoolExecutor:
    """Create the signal worker pool lazily instead of at module import."""
    global _signal_executor
    if _signal_executor is None:
        _signal_executor = ThreadPoolExecutor(
            max_workers=SIGNAL_WORKER_COUNT,
            thread_name_prefix="signal-worker",
        )
    return _signal_executor

def _init_db():
    context_repo.init_core_tables(DB_PATH)

def run_startup_tasks() -> None:
    """Execute non-critical startup tasks. Call explicitly from an entrypoint
    or from tests by passing run_startup=True to `create_app()` when safe.
    """
    global _STARTUP_TASKS_RAN
    try:
        _init_db()
    except Exception as e:
        logger.error(f"DB init failed during startup: {e}")

    try:
        ensure_recent_favorable_setups_table()
        prune_recent_favorable_setups(RECENT_FAVORABLE_SETUP_TTL_MINUTES)
    except Exception as e:
        logger.error(f"Recent favorable setups init failed: {e}")

    try:
        init_session_momentum_table()
    except Exception as e:
        logger.error(f"Session momentum table initialization failed: {e}")

    try:
        init_db_performance_indexes()
        logger.info("DB performance indexes initialized")
    except Exception as e:
        logger.error(f"DB performance index initialization failed: {e}")

    try:
        start_prediction_cache_loader()
        logger.info(f"Prediction cache loader started: {prediction_cache_status()}")
    except Exception as e:
        logger.error(f"Prediction cache loader startup failed: {e}")

    try:
        _get_signal_executor()
    except Exception as e:
        logger.error(f"Signal executor startup failed: {e}")

    try:
        _startup_reconcile()
    except Exception as e:
        logger.error(f"Startup reconciliation hook failed: {e}")

    try:
        _load_symbol_overrides()
    except Exception as e:
        logger.error(f"Symbol override startup load failed: {e}")

    try:
        _build_trend_table()
    except Exception as e:
        logger.error(f"Trend-table startup build failed: {e}")

    try:
        _hydrate_cooldowns()
    except Exception as e:
        logger.error(f"Cooldown startup hydration failed: {e}")

    try:
        _hydrate_recent_sells()
    except Exception as e:
        logger.error(f"Recent-sell startup hydration failed: {e}")

    try:
        _load_market_context()
    except Exception as e:
        logger.error(f"Market-context startup load failed: {e}")

    _STARTUP_TASKS_RAN = True


def _register_routes(flask_app: Flask, app_container: ApplicationContainer) -> None:
    """Register HTTP blueprints against a Flask app instance."""
    auth = RequestAuthService(validate_secret=validate_secret)
    responses = ResponseFactory()

    flask_app.register_blueprint(create_webhook_blueprint(WebhookRouteDeps(
        auth=auth,
        parser=WebhookPayloadParser(APPROVED_SYMBOLS, PRICE_RANGES, logger),
        responses=responses,
        make_dedupe_key=_make_dedupe_key,
        record_webhook_event=_record_webhook_event,
        mark_webhook_event_status=(
            lambda dedupe_key, status, **kwargs: _trade_audit_recorder().record_webhook_status(
                dedupe_key=dedupe_key,
                status=status,
                **kwargs,
            )
        ),
        submit_signal=lambda data: app_container.signal_executor_factory().submit(process_signal, data),
        logger=logger,
    )))
    flask_app.register_blueprint(create_status_blueprint(StatusRouteDeps(
        auth=auth,
        responses=responses,
        health_payload=health_payload,
        status_payload=status_payload,
        positions_payload=positions_payload,
    )))
    flask_app.register_blueprint(create_debug_blueprint(DebugRouteDeps(
        auth=auth,
        responses=responses,
        debug_symbol_payload=debug_symbol_payload,
    )))


def create_app(
    run_startup: bool = False,
    app_container: ApplicationContainer | None = None,
) -> Flask:
    """Application factory.

    Returns a new Flask app instance with the module's routes registered.
    When `run_startup` is True, execute non-critical startup tasks explicitly.
    """
    app_container = app_container or container
    if run_startup:
        run_startup_tasks()
    flask_app = Flask(__name__)
    flask_app.extensions["application_container"] = app_container
    _register_routes(flask_app, app_container)
    return flask_app

def _startup_reconcile():
    try:
        # 1. Check required env vars
        for key in ("ANTHROPIC_API_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
            if not os.environ.get(key):
                logger.error(f"Startup: missing required environment variable {key}")

        # 2. Fetch Alpaca positions
        try:
            alpaca_positions = broker_service.list_positions()
            alpaca_symbols = {p.symbol for p in alpaca_positions}
        except Exception as e:
            logger.error(f"Startup reconciliation: failed to fetch Alpaca positions: {e}")
            alpaca_symbols = set()
            alpaca_positions = []

        # 3. Query DB for symbols with a net open position (more filled buys than sells)
        db_symbols = set()
        try:
            rows = context_repo.startup_db_open_symbols()
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

def _ml_prediction_bucket(score) -> str:
    return entry_policy.ml_prediction_bucket(score)

def _buy_opportunity_sizing_enabled() -> bool:
    return os.getenv("BUY_OPPORTUNITY_SIZING_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _get_bars_with_fallback(symbol: str, timeframe: str, **kwargs):
    return market_data_service.get_bars_with_fallback(symbol, timeframe, **kwargs)


def get_account():
    return broker_service.get_account()


def get_position(symbol):
    return broker_service.get_position(symbol)


def place_order(*args, **kwargs):
    return broker_service.place_order(*args, **kwargs)


def build_tape_context(*args, **kwargs):
    return tape_service.build_tape_context(*args, **kwargs)


def evaluate_buy_opportunity(
    *,
    trend,
    setup_obs,
    bias_entry,
    macro_risk,
    session_momentum,
    momentum,
    prediction_gate=None,
    recent_favorable_setup=None,
    adaptive_buy_confirmation=None,
):
    return entry_policy.evaluate_buy_opportunity(
        trend=trend,
        setup_obs=setup_obs,
        bias_entry=bias_entry,
        macro_risk=macro_risk,
        session_momentum=session_momentum,
        momentum=momentum,
        prediction_gate=prediction_gate,
        recent_favorable_setup=recent_favorable_setup,
        adaptive_buy_confirmation=adaptive_buy_confirmation,
    )


def _ml_prediction_compare_decision(prediction: dict | None) -> str | None:
    return entry_policy.ml_prediction_compare_decision(prediction)


def evaluate_signal_quality_gate(
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
    ml_prediction=None,
):
    return entry_policy.evaluate_signal_quality_gate(
        trend_direction=trend_direction,
        trend_strength=trend_strength,
        market_bias=market_bias,
        setup_label=setup_label,
        setup_policy_action=setup_policy_action,
        momentum_direction=momentum_direction,
        momentum_pct=momentum_pct,
        consecutive_buy_count=consecutive_buy_count,
        recent_favorable_setup=recent_favorable_setup,
        ml_prediction=ml_prediction,
    )


def evaluate_prediction_gate(**kwargs):
    """Backward-compatible alias for the deterministic signal-quality gate."""
    return entry_policy.evaluate_prediction_gate(**kwargs)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "changeme")

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
    """Return True if the same symbol/action/rounded-price arrived recently."""
    try:
        key = _webhook_dedupe_key(symbol, action, price)
        return cooldown_repo.recent_webhook_seen(
            key, symbol, action, price, WEBHOOK_DEDUPE_SECONDS
        )
    except Exception as e:
        logger.error(f"_is_duplicate_webhook failed for {symbol}/{action}: {e}")
        return False


def _successful_buys_today(symbol):
    try:
        return trades_repo.successful_buys_today(symbol)
    except Exception as e:
        logger.error(f"_successful_buys_today failed for {symbol}: {e}")
        return 0


def _filled_buys_today(symbol):
    try:
        return trades_repo.filled_buys_today(symbol)
    except Exception as e:
        logger.error(f"_filled_buys_today failed for {symbol}: {e}")
        return 0


def _has_open_position_db(symbol):
    try:
        return trades_repo.has_open_position(symbol)
    except Exception:
        return True  # fail-open: never silently block a sell on DB error

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


def _compute_trend(recent_actions: list) -> dict:
    return trend_context_service.compute_trend(recent_actions)

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
        rows = trades_repo.recent_signal_history(approved)

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

def _hydrate_cooldowns():
    try:
        current_et = now_et()
        rows = cooldown_repo.cooldown_rows()
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

def _hydrate_recent_sells():
    try:
        current_et = now_et()
        rows = cooldown_repo.recent_sell_rows()
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


def _read_cooldown(symbol, action):
    try:
        row = cooldown_repo.read_cooldown(symbol, action)
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
    try:
        row = cooldown_repo.read_recent_sell(symbol)
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
    try:
        cooldown_repo.write_cooldown(symbol, action, ts.isoformat())
    except Exception as e:
        logger.error(f"_write_cooldown failed for {symbol}/{action}: {e}")


def _write_recent_sell(symbol, ts, price):
    try:
        cooldown_repo.write_recent_sell(symbol, ts.isoformat(), price)
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
        rows = trades_repo.recent_actions_for_trend(symbol)
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
        expected_date = expected_market_context_date().isoformat()
        _market_bias.clear()
        if market_date != expected_date:
            logger.warning(
                "market_context.json is stale "
                f"(market_date={market_date}, expected={expected_date}) — cleared market bias"
            )
            return
        symbols = ctx.get("symbols") or {}
        for sym, entry in symbols.items():
            if isinstance(entry, dict) and entry.get("bias") in ("buy", "avoid", "neutral"):
                enriched_entry = dict(entry)
                enriched_entry.setdefault("bias", entry["bias"])
                enriched_entry.setdefault("reason", "")
                enriched_entry.setdefault("confidence", "")
                enriched_entry.setdefault("fundamental_score", None)
                enriched_entry.setdefault("risk_level", None)
                enriched_entry.setdefault("entry_quality", None)
                enriched_entry.setdefault("avoid_type", None)
                _market_bias[sym] = enriched_entry
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

def _make_dedupe_key(data):
    return dedupe_service.make_dedupe_key(data)


def _record_webhook_event(dedupe_key, data):
    try:
        return dedupe_service.record_webhook_event(dedupe_key, data, WEBHOOK_DEDUPE_SECONDS)
    except Exception as e:
        logger.error(f"Webhook dedupe persistence failed: {e}")
        return True


def _trade_audit_recorder():
    return trade_audit_service.TradeAuditService(
        market_bias=_market_bias,
        trend_table=_trend_table,
        ml_prediction_bucket=_ml_prediction_bucket,
        log=logger,
        mark_webhook_event_status=dedupe_service.mark_webhook_event_status,
    )


def _context_assembly_deps():
    return ContextAssemblyDeps(
        execution_mode=EXECUTION_MODE,
        market_bias=_market_bias,
        trend_table=_trend_table,
        rolling_symbol_context=rolling_symbol_context,
        prior_session_context=prior_session_context,
        build_tape_context=build_tape_context,
        get_momentum=get_momentum,
        setup_context_deps=SetupContextDeps(
            build_snapshot=build_snapshot,
            evaluate_setup_policy=evaluate_setup_policy,
            upsert_recent_favorable_setup=upsert_recent_favorable_setup,
            get_recent_favorable_setup=get_recent_favorable_setup,
            now=datetime.now,
            recent_favorable_setup_ttl_minutes=RECENT_FAVORABLE_SETUP_TTL_MINUTES,
            log=logger,
        ),
        log=logger,
    )

def validate_secret(req):
    auth_header = req.headers.get("Authorization", "")
    bearer_secret = ""
    if auth_header.lower().startswith("bearer "):
        bearer_secret = auth_header.split(" ", 1)[1].strip()

    secret = (
        req.headers.get("X-Webhook-Secret")
        or bearer_secret
        or req.args.get("secret", "")
    )
    if secret != WEBHOOK_SECRET:
        logger.warning(f"Invalid secret from {req.remote_addr}")
        abort(401)
    if req.args.get("secret"):
        logger.warning("Secret accepted from query parameter; prefer X-Webhook-Secret or Authorization header")

def log_trade(signal, decision, order, account_state=None):
    return _trade_audit_recorder().record_execution(
        signal=signal,
        decision=decision,
        order=order,
        account_state=account_state,
    )


def _build_decision_context(symbol, action, account_state=None):
    return trade_audit_service.build_decision_context(
        symbol,
        action,
        account_state,
        market_bias=_market_bias,
        trend_table=_trend_table,
        log=logger,
    )

def log_rejection(symbol, action, category, reason, price=None, account_state=None):
    return _trade_audit_recorder().record_rejection(
        symbol=symbol,
        action=action,
        category=category,
        reason=reason,
        price=price,
        account_state=account_state,
    )

def _open_entry_context(symbol):
    """Return the oldest currently-open buy lot context for a symbol."""
    try:
        rows = trades_repo.open_entry_rows(symbol)
        lots = []
        for r in rows:
            qty = float(r["qty"] or 0)
            if qty <= 0:
                continue
            action = (r["action"] or "").lower()
            if action == "buy":
                lots.append({"remaining_qty": qty, "row": r})
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


def _weekly_symbol_performance(symbol: str) -> dict:
    try:
        return trades_repo.weekly_symbol_performance(symbol)
    except Exception as e:
        return {"label": "error", "error": str(e)}


def _required_buy_confirmations(symbol, account_state=None):
    return entry_policy.required_buy_confirmations(
        symbol,
        account_state,
        load_market_context=_load_market_context,
        market_bias=_market_bias,
        get_macro_risk=get_macro_risk,
        base_dir=Path(__file__).parent,
        symbol_market_alignment=_symbol_market_alignment,
        log=logger,
    )

def _required_sell_confirmations(symbol, account_state=None):
    return entry_policy.required_sell_confirmations(symbol, account_state)

def _symbol_market_alignment(symbol):
    try:
        return trend_context_service.symbol_market_alignment(
            symbol,
            symbol_market_alignment_map=SYMBOL_MARKET_ALIGNMENT,
            market_bias=_market_bias,
            trend_table=_trend_table,
            signal_history=_signal_history,
            load_market_context=_load_market_context,
            refresh_signal_history=_refresh_signal_history,
        )

    except Exception as e:
        logger.error(f"_symbol_market_alignment failed for {symbol}: {e}")
        return {
            "cluster": "unknown",
            "benchmark": None,
            "aligned_for_buy": None,
            "reason": f"alignment error: {e}",
        }

def _one_bar_confirmation_hold(symbol: str, signal_price: float, account_state: dict) -> tuple[bool, str]:
    return entry_policy.one_bar_confirmation_hold(
        symbol,
        signal_price,
        account_state,
        enabled=ONE_BAR_CONFIRMATION_HOLD_ENABLED,
        extension_threshold_pct=ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT,
        timeout_seconds=ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS,
        get_bars_with_fallback=_get_bars_with_fallback,
    )

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

def _cluster_exposure(symbol, balance):
    """Return cluster exposure info for the symbol across current Alpaca positions."""
    if not balance:
        return []

    results = []
    try:
        positions = broker_service.list_positions()
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
        # SIP = consolidated tape (NYSE/NASDAQ/all venues). IEX captures only a
        # fraction of volume for high-volume names, making surge detection unreliable.
        bars = _get_bars_with_fallback(symbol, '1Min', start=start, feed='sip')

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
            "momentum_pct": round(momentum_5m_pct, 3),   # preserve existing field name
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
            "volume_note": "iex_thin" if symbol in IEX_THIN_SYMBOLS else None,
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


def _sell_continuation_delay_reason(account_state, trend, unrealized_pct):
    """
    Return a rejection reason when a normal webhook SELL looks early.

    This protects against indicator-alert noise cutting a position while the
    latest session tape still supports continuation. Hard loss exits and broker
    brackets do not use this path.
    """
    enabled = os.getenv("SELL_CONTINUATION_CHECK_ENABLED", "true").strip().lower()
    if enabled not in ("1", "true", "yes", "on"):
        return None

    unrealized_pct = _safe_float(unrealized_pct)
    if unrealized_pct is None:
        return None

    hard_loss_floor = _env_float("SELL_CONTINUATION_HARD_LOSS_FLOOR_PCT", -0.75)
    if unrealized_pct <= hard_loss_floor:
        return None

    session = (account_state or {}).get("session_momentum") or {}
    trend = trend or {}

    session_score = _safe_float(session.get("trend_score"))
    session_5m = _safe_float(session.get("momentum_5m_pct"))
    session_15m = _safe_float(session.get("momentum_15m_pct"))
    session_30m = _safe_float(session.get("momentum_30m_pct"))
    vwap_dist = _safe_float(session.get("distance_from_vwap_pct"))
    session_label = session.get("trend_label")

    if session_5m is not None and session_5m <= _env_float("SELL_CONTINUATION_MAX_5M_DROP_PCT", -0.20):
        return None
    if session_15m is not None and session_15m <= _env_float("SELL_CONTINUATION_MAX_15M_DROP_PCT", -0.10):
        return None

    supports = []
    min_momentum = _env_float("SELL_CONTINUATION_MIN_MOMENTUM_PCT", 0.15)
    min_vwap_dist = _env_float("SELL_CONTINUATION_MIN_VWAP_DIST_PCT", 0.10)
    min_session_score = _env_float("SELL_CONTINUATION_MIN_SESSION_SCORE", 2.0)

    if session_15m is not None and session_15m >= min_momentum:
        supports.append(f"15m={session_15m:.3f}%")
    if session_30m is not None and session_30m >= min_momentum:
        supports.append(f"30m={session_30m:.3f}%")
    if vwap_dist is not None and vwap_dist >= min_vwap_dist:
        supports.append(f"vwap_dist={vwap_dist:.3f}%")
    if session_score is not None and session_score >= min_session_score:
        supports.append(f"session_score={session_score:.1f}")

    direction = trend.get("direction")
    strength = trend.get("strength")
    consecutive_count = int(trend.get("consecutive_count") or 0)
    strong_bearish_pressure = (
        direction == "bearish"
        and strength == "confirmed"
        and consecutive_count >= 3
    )

    required_support_count = int(os.getenv("SELL_CONTINUATION_MIN_SUPPORTS", "2"))
    if len(supports) >= required_support_count and not strong_bearish_pressure:
        return (
            "sell continuation check: "
            f"unrealized={unrealized_pct:.2f}% "
            f"session_label={session_label} "
            f"trend={direction}/{strength} count={consecutive_count}; "
            f"supports={', '.join(supports)}"
        )

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
    quote = market_data_service.get_latest_quote(symbol)

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

PORTFOLIO_ROTATION_ENABLED = os.environ.get("PORTFOLIO_ROTATION_ENABLED", "false").lower().strip() in (
    "1", "true", "yes", "on"
)
PORTFOLIO_ROTATION_MIN_CANDIDATE_SCORE = int(os.environ.get("PORTFOLIO_ROTATION_MIN_CANDIDATE_SCORE", "12"))
PORTFOLIO_ROTATION_MAX_PER_DAY = int(os.environ.get("PORTFOLIO_ROTATION_MAX_PER_DAY", "2"))
PORTFOLIO_ROTATION_MIN_HOLD_MINUTES = int(os.environ.get("PORTFOLIO_ROTATION_MIN_HOLD_MINUTES", "30"))
PORTFOLIO_ROTATION_MAX_WEAK_PLPC = float(os.environ.get("PORTFOLIO_ROTATION_MAX_WEAK_PLPC", "0.0"))

PORTFOLIO_ROTATION_EXCLUDED_SYMBOLS = {
    s.strip().upper()
    for s in os.environ.get("PORTFOLIO_ROTATION_EXCLUDED_SYMBOLS", "SPY,QQQ,GLD,IWM").split(",")
    if s.strip()
}

PORTFOLIO_ROTATION_ALLOWED_RISK_LEVELS = {
    s.strip().lower()
    for s in os.environ.get("PORTFOLIO_ROTATION_ALLOWED_RISK_LEVELS", "low,medium").split(",")
    if s.strip()
}

PORTFOLIO_ROTATION_ALLOWED_ENTRY_QUALITIES = {
    s.strip().lower()
    for s in os.environ.get(
        "PORTFOLIO_ROTATION_ALLOWED_ENTRY_QUALITIES",
        "excellent,high,good_on_pullbacks,good_if_holds_gap,good_if_breadth_holds"
    ).split(",")
    if s.strip()
}



def _portfolio_rotation_count_today():
    try:
        return trades_repo.portfolio_rotation_count_today()
    except Exception as e:
        logger.error(f"_portfolio_rotation_count_today failed: {e}")
        return 999


def _rotation_candidate_score(symbol, account_state):
    """Score a capped BUY candidate for portfolio rotation without calling Claude."""
    score = 0
    reasons = []

    trend = _trend_table.get(symbol) or {}
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

    bias = _market_bias.get(symbol) or {}
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

    if risk_level not in PORTFOLIO_ROTATION_ALLOWED_RISK_LEVELS:
        return 0, f"risk_level={risk_level} not allowed"
    score += 2
    reasons.append(f"risk={risk_level}")

    if entry_quality not in PORTFOLIO_ROTATION_ALLOWED_ENTRY_QUALITIES:
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


def _weakest_rotation_holding(candidate_symbol):
    """Return the weakest replaceable Alpaca long position, or None."""
    try:
        positions = broker_service.list_positions()
    except Exception as e:
        logger.error(f"_weakest_rotation_holding failed to fetch positions: {e}")
        return None

    candidates = []

    for pos in positions:
        try:
            sym = str(pos.symbol).upper()

            if sym == candidate_symbol:
                continue

            if sym in PORTFOLIO_ROTATION_EXCLUDED_SYMBOLS:
                continue

            qty = float(pos.qty)
            if qty <= 0:
                continue

            plpc = float(pos.unrealized_plpc) * 100.0
            current_price = float(pos.current_price)

            entry_ctx = _open_entry_context(sym) or {}
            holding_minutes = entry_ctx.get("holding_minutes")

            if holding_minutes is not None and holding_minutes < PORTFOLIO_ROTATION_MIN_HOLD_MINUTES:
                continue

            if plpc > PORTFOLIO_ROTATION_MAX_WEAK_PLPC:
                continue

            trend = _trend_table.get(sym) or {}

            candidates.append({
                "symbol": sym,
                "qty": qty,
                "current_price": current_price,
                "unrealized_plpc": round(plpc, 3),
                "trend_direction": trend.get("direction"),
                "trend_strength": trend.get("strength"),
                "holding_minutes": holding_minutes,
            })
        except Exception as e:
            logger.warning(f"_weakest_rotation_holding skipped a position: {e}")

    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda x: (
            x["unrealized_plpc"],
            x["holding_minutes"] if x["holding_minutes"] is not None else 999999,
        )
    )[0]


def _try_portfolio_rotation(candidate_symbol, candidate_price, account_state, now_dt):
    return execution_policy.try_portfolio_rotation(
        candidate_symbol=candidate_symbol,
        candidate_price=candidate_price,
        account_state=account_state,
        now_dt=now_dt,
        enabled=PORTFOLIO_ROTATION_ENABLED,
        max_per_day=PORTFOLIO_ROTATION_MAX_PER_DAY,
        min_candidate_score=PORTFOLIO_ROTATION_MIN_CANDIDATE_SCORE,
        rotation_count_today=_portfolio_rotation_count_today,
        rotation_candidate_score=_rotation_candidate_score,
        weakest_rotation_holding=_weakest_rotation_holding,
        place_order=place_order,
        log_trade=log_trade,
        last_order=_last_order,
        write_cooldown=_write_cooldown,
        last_sell=_last_sell,
        write_recent_sell=_write_recent_sell,
        logger=logger,
    )

def _pre_order_safety_check(symbol, action, signal_price, account_state):
    return execution_policy.pre_order_safety_check(
        symbol=symbol,
        action=action,
        signal_price=signal_price,
        account_state=account_state,
        market_data_service=market_data_service,
        broker_service=broker_service,
        validate_spread_with_retry=_validate_spread_with_retry,
        symbol_max_spread_pct=SYMBOL_MAX_SPREAD_PCT,
        max_bid_ask_spread_pct=MAX_BID_ASK_SPREAD_PCT,
        max_signal_price_drift_pct=MAX_SIGNAL_PRICE_DRIFT_PCT,
        logger=logger,
    )

def _get_weakest_position_context(account_state):
    """
    Observe-only helper.

    Finds the weakest currently held position using available account_state
    position data. This does not trade. It only enriches macro position limit
    rejection reasons so we can evaluate future replacement logic.
    """
    positions = account_state.get("open_positions") or account_state.get("positions") or []

    weakest = None

    for p in positions:
        try:
            symbol = p.get("symbol")
            unrealized_plpc = float(
                p.get("unrealized_plpc")
                or p.get("unrealized_pl_pct")
                or p.get("unrealized_plpc_pct")
                or 0
            )
            market_value = float(p.get("market_value") or 0)

            # Lower score is worse. We heavily penalize red positions.
            weakness_score = unrealized_plpc

            item = {
                "symbol": symbol,
                "unrealized_plpc": unrealized_plpc,
                "market_value": market_value,
                "weakness_score": weakness_score,
            }

            if weakest is None or weakness_score < weakest["weakness_score"]:
                weakest = item

        except Exception:
            continue

    return weakest

def _count_second_look_blocks_today(symbol):
    try:
        return trades_repo.second_look_blocks_today(symbol)
    except Exception as e:
        logger.warning(f"Failed to count second-look blocks for {symbol}: {e}")
        return 0

def _adaptive_churn_reentry_allowed(symbol, signal_price, last_sell_price, account_state):
    """
    Return (allowed, reason) for a BUY near the last sell price.

    Default behavior remains conservative. This only allows re-entry when live
    evidence suggests the new signal is a legitimate continuation/recovery setup
    rather than chop around the prior exit.
    """
    if not ENFORCE_ADAPTIVE_CHURN_REENTRY:
        return False, "adaptive churn re-entry disabled"

    try:
        signal_price = float(signal_price)
        last_sell_price = float(last_sell_price)
    except (TypeError, ValueError):
        return False, "invalid signal/last-sell price"

    if signal_price <= 0 or last_sell_price <= 0:
        return False, "invalid signal/last-sell price"

    price_vs_last_sell_pct = (signal_price - last_sell_price) / last_sell_price * 100

    # Do not re-enter below the prior sell. That is more likely churn than improvement.
    if price_vs_last_sell_pct < 0:
        return False, f"signal below last sell by {price_vs_last_sell_pct:.3f}%"

    trend = _trend_table.get(symbol) or {}
    trend_direction = trend.get("direction")
    trend_strength = trend.get("strength")
    consecutive_count = int(trend.get("consecutive_count") or 0)
    last_signal = trend.get("last_signal")

    setup_obs = (account_state or {}).get("setup_observation") or {}
    setup_label = setup_obs.get("setup_label")
    setup_policy_action = setup_obs.get("setup_policy_action")

    recent_favorable_setup = (account_state or {}).get("recent_favorable_setup")

    favorable_setup = (
        setup_policy_action in ("boost", "allow")
        or is_favorable_setup_label(setup_label)
        or bool(recent_favorable_setup)
    )

    trend_ok = (
        trend_direction == "bullish"
        and last_signal == "buy"
        and consecutive_count >= 3
        and trend_strength in ("developing", "confirmed")
    )

    if trend_ok and favorable_setup:
        return (
            True,
            "adaptive churn re-entry allowed: "
            f"price_vs_last_sell={price_vs_last_sell_pct:.3f}%, "
            f"trend={trend_direction}/{trend_strength}, "
            f"count={consecutive_count}, "
            f"setup_label={setup_label}, "
            f"setup_policy_action={setup_policy_action}, "
            f"recent_favorable_setup={bool(recent_favorable_setup)}"
        )

    return (
        False,
        "adaptive churn re-entry not strong enough: "
        f"price_vs_last_sell={price_vs_last_sell_pct:.3f}%, "
        f"trend={trend_direction}/{trend_strength}, "
        f"count={consecutive_count}, "
        f"last_signal={last_signal}, "
        f"setup_label={setup_label}, "
        f"setup_policy_action={setup_policy_action}, "
        f"recent_favorable_setup={bool(recent_favorable_setup)}"
    )


def _legacy_process_signal(data):
    dedupe_key = data.get("_dedupe_key")
    ...
    _load_market_context()
    symbol, action = normalize_signal_identity(data)
    price = data.get("price", 0)
    logger.info(f"Processing {action.upper()} signal for {symbol} at {price}")

    account_state = get_mock_account_state()
    runtime_state = SignalRuntimeState(
        raw_signal=data,
        symbol=symbol,
        action=action,
        received_at=datetime.now(timezone.utc),
        account_state=account_state,
    )

    context_runtime = build_legacy_signal_context(
        runtime_state,
        _context_assembly_deps(),
    )
    built_context = context_runtime.built
    setup_obs = built_context.setup.data

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
            _trade_audit_recorder().record_webhook_status(
                dedupe_key=dedupe_key,
                status="rejected",
                failure_reason=format_rejection_reason(category, reason),
            )

        return True

    def _reject_approval_decision(approval: ApprovalDecision, level="warning"):
        return _reject_current_signal(
            approval.category or "approval_rejection",
            approval.reason,
            level=level,
        )

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

    if (
        action == "buy"
        and ENFORCE_SETUP_POLICY_BLOCKS
        and setup_obs.get("setup_policy_action") == "block"
    ):
        setup_label = setup_obs.get("setup_label") or ""
        reason = setup_obs.get("setup_policy_reason") or "setup_policy:block"

        session_label = account_state.get("session_trend_label")
        session_score = float(account_state.get("session_trend_score") or 0)
        session_m5 = float(account_state.get("session_momentum_5m_pct") or 0)
        session_m15 = float(account_state.get("session_momentum_15m_pct") or 0)
        session_m30 = float(account_state.get("session_momentum_30m_pct") or 0)
        session_vwap = float(account_state.get("session_distance_from_vwap_pct") or 0)

        stretched_but_confirmed = (
            setup_label == "avoid_stretched_above_vwap_strength"
            and session_label == "strong_uptrend"
            and session_score >= 6
            and session_m5 > 0
            and session_m15 > 0
            and session_m30 > 0
            and session_vwap <= 1.75
        )

        if stretched_but_confirmed:
            account_state["setup_policy_override"] = {
                "from": "block",
                "to": "allow_reduced_size",
                "reason": (
                    f"stretched setup allowed reduced-size due to confirmed session strength: "
                    f"label={session_label} score={session_score} "
                    f"5m={session_m5:.3f}% 15m={session_m15:.3f}% "
                    f"30m={session_m30:.3f}% vwap={session_vwap:.3f}%"
                ),
            }
            apply_size_cap(
                account_state,
                cap_pct=0.75,
                state_key="setup_policy_size_cap",
                payload={"cap_pct": 0.75, "source": "setup_policy_override"},
            )

            logger.warning(
                f"Setup policy override for {symbol}: "
                f"{account_state['setup_policy_override']['reason']}"
            )
        else:
            if _reject_approval_decision(
                setup_policy_rejection(
                    reason,
                    metadata={"setup_label": setup_label},
                )
            ):
                return

    # Degraded-setup size cap: when build_snapshot() fails entirely the bot has
    # no setup label, no score, and no classification data.  Unknown setups have
    # historically lost at a higher rate, so cap position size materially rather
    # than letting Claude assign a full-size buy on missing data.
    #
    # Strong-context exception: confirmed or developing bullish trend allows 1.0%
    # cap instead of 0.75%, letting the trade proceed at a reduced but not
    # minimal size if the trend context is positive.
    #
    # Bad-context examples that do NOT qualify: neutral trend, non-bullish, missing data.
    if action == "buy" and setup_obs.get("setup_policy_action") == "error":
        _deg_trend = _trend_table.get(symbol) or {}
        _deg_trend_dir = _deg_trend.get("direction")
        _deg_trend_str = _deg_trend.get("strength")
        _has_strong_context = (
            _deg_trend_dir == "bullish"
            and _deg_trend_str in ("confirmed", "developing")
        )
        _deg_cap = 1.0 if _has_strong_context else 0.75
        apply_size_cap(
            account_state,
            cap_pct=_deg_cap,
            state_key="setup_degraded",
            payload={
                "reason": setup_obs.get("setup_unknown_reason") or "build_snapshot_failed",
                "size_cap_pct": _deg_cap,
                "has_strong_context": _has_strong_context,
                "trend_direction": _deg_trend_dir,
                "trend_strength": _deg_trend_str,
            },
        )
        logger.warning(
            f"Degraded setup (error) for {symbol}: size capped at {_deg_cap}%, "
            f"strong_context={_has_strong_context} "
            f"({_deg_trend_dir}/{_deg_trend_str}), "
            f"reason={setup_obs.get('setup_unknown_reason')}"
        )

    # Unrecognized label cap: taxonomy drift (new or misspelled setup_label) currently
    # passes as "neutral" action but represents unknown territory.  Apply a mild size
    # reduction so it behaves like degraded-lite rather than a known-good neutral setup.
    if action == "buy" and is_unrecognized_setup_label(setup_obs):
        _unrecog_cap = _env_float("UNRECOGNIZED_LABEL_SIZE_CAP_PCT", 0.85)
        apply_size_cap(
            account_state,
            cap_pct=_unrecog_cap,
            state_key="unrecognized_label_cap",
            payload={
                "setup_unknown_reason": setup_obs.get("setup_unknown_reason"),
                "cap_pct": _unrecog_cap,
            },
        )
        logger.warning(
            f"Unrecognized setup label size cap for {symbol}: "
            f"{setup_obs.get('setup_unknown_reason')} → {_unrecog_cap}%"
        )

    # Late rollover entry gate:
    # Blocks GEV-style late buys where price has already run, is extended
    # above VWAP, and intermediate session momentum is rolling over.
    #
    # Example blocked pattern:
    # setup_label=late_strength_near_vwap_risk
    # session_return_pct > 1.5
    # session_distance_from_vwap_pct > 1.0
    # session_momentum_15m_pct < 0
    # session_momentum_30m_pct < 0
    if action == "buy":
        setup_label = setup_obs.get("setup_label") or ""

        session_return_pct = float(account_state.get("session_return_pct") or 0)
        session_vwap_dist_pct = float(account_state.get("session_distance_from_vwap_pct") or 0)
        session_m15_pct = float(account_state.get("session_momentum_15m_pct") or 0)
        session_m30_pct = float(account_state.get("session_momentum_30m_pct") or 0)

        if (
            setup_label == "late_strength_near_vwap_risk"
            and session_return_pct > 1.5
            and session_vwap_dist_pct > 1.0
            and session_m15_pct < 0
            and session_m30_pct < 0
        ):
            reason = (
                f"late rollover entry blocked: setup_label={setup_label}, "
                f"session_return={session_return_pct:.3f}%, "
                f"vwap_dist={session_vwap_dist_pct:.3f}%, "
                f"15m={session_m15_pct:.3f}%, "
                f"30m={session_m30_pct:.3f}%"
            )
            if _reject_current_signal("late_rollover_entry", reason):
                return

    # Late-after-quote-delay gate:
    # If repeated second-look quote-quality checks blocked earlier entries,
    # avoid finally buying later when the clean part of the move may be gone.
    #
    # This targets LMT-style entries:
    # - multiple earlier second-look spread blocks
    # - current setup is weaker / transitional
    # - session has already moved meaningfully
    # - prediction is watch/neutral rather than a clean pass
    if action == "buy":
        second_look_blocks = _count_second_look_blocks_today(symbol)
        setup_label = setup_obs.get("setup_label") or ""

        prediction_gate = account_state.get("prediction_gate") or {}
        prediction_decision = (
            prediction_gate.get("prediction_decision")
            or prediction_gate.get("decision")
            or ""
        )

        session_score = float(account_state.get("session_trend_score") or 0)
        session_return_pct = float(account_state.get("session_return_pct") or 0)

        if (
            second_look_blocks >= int(os.getenv("LATE_QUOTE_DELAY_MIN_BLOCKS", "3"))
            and setup_label in {"unclassified_transition", "balanced_transition_state"}
            and str(prediction_decision).lower() in {"watch", "neutral", "none", ""}
            and session_return_pct >= float(os.getenv("LATE_QUOTE_DELAY_MIN_SESSION_RETURN_PCT", "0.75"))
            and session_score <= float(os.getenv("LATE_QUOTE_DELAY_MAX_SESSION_SCORE", "5"))
        ):
            reason = (
                f"late entry after repeated second-look quote blocks: "
                f"second_look_blocks={second_look_blocks}, "
                f"setup_label={setup_label}, "
                f"prediction_decision={prediction_decision}, "
                f"session_score={session_score:.1f}, "
                f"session_return={session_return_pct:.3f}%"
            )
            if _reject_current_signal("late_after_quote_delay", reason):
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
            buys_today = trades_repo.cash_safe_buys_today(symbol)
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

    preflight = PreflightService(
        PreflightDeps(
            now_et=now_et,
            is_market_hours=is_market_hours,
            assert_position_exists=broker_service.assert_position_exists,
            get_position=get_position,
            read_cooldown=_read_cooldown,
            read_recent_sell=_read_recent_sell,
            is_duplicate_webhook=_is_duplicate_webhook,
            adaptive_churn_reentry_allowed=_adaptive_churn_reentry_allowed,
            successful_buys_today=_successful_buys_today,
            filled_buys_today=_filled_buys_today,
            cluster_exposure=_cluster_exposure,
            max_buys_per_symbol_per_day=MAX_BUYS_PER_SYMBOL_PER_DAY,
            session_max_trade_count=int(os.getenv("SESSION_MAX_TRADE_COUNT", "3")),
            webhook_dedupe_seconds=WEBHOOK_DEDUPE_SECONDS,
            daily_loss_limit_pct=DAILY_LOSS_LIMIT_PCT,
        )
    )
    preflight_result = preflight.evaluate(runtime_state)
    current_et = preflight_result.metadata.get("current_et") or now_et()
    existing_position = preflight_result.metadata.get("existing_position")
    if not preflight_result.allowed:
        if _reject_current_signal(
            preflight_result.rejection_category,
            preflight_result.rejection_reason,
            level=preflight_result.metadata.get("log_level", "warning"),
        ):
            return

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

    cooldown_key = (symbol, action)

    # Observe-only BUY opportunity score before macro position-limit checks.
    # This ensures macro_position_limit rejections still get scored for replacement intelligence.
    if action == "buy" and "buy_opportunity" not in account_state:
        try:
            trend = _trend_table.get(symbol) or {}
            bias_entry = _market_bias.get(symbol) or {}
            context_runtime.build_buy_opportunity_observation(
                trend=trend,
                bias_entry=bias_entry,
                evaluate_buy_opportunity=evaluate_buy_opportunity,
                required_buy_confirmations=_required_buy_confirmations,
                log_prefix="BUY opportunity pre-macro",
            )
        except Exception as e:
            logger.warning(f"BUY opportunity pre-macro scoring failed for {symbol}: {e}")

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
        _open_positions_list = account_state.get("open_positions") or []
        if _open_positions_list:
            effective_count = sum(
                1 for p in _open_positions_list
                if float(p.get("market_value") or 0) >= MACRO_POSITION_COUNT_FLOOR
            )
        else:
            effective_count = open_count
        if effective_count >= max_new_positions:
            # Enrich observe-only macro-position-limit logging with the latest
            # session momentum snapshot. The main session_momentum block runs
            # later in the pipeline, but macro_position_limit rejects before that,
            # so account_state will not have these fields yet.
            candidate_session = None
            try:
                candidate_session = get_latest_session_momentum(symbol)
                if candidate_session and not _session_momentum_is_fresh(candidate_session):
                    candidate_session = None
            except Exception as e:
                logger.warning(f"macro_position_limit session lookup failed for {symbol}: {e}")
                candidate_session = None

            if candidate_session:
                account_state["session_momentum"] = candidate_session

            def _session_value(key, fallback_key=None):
                if candidate_session and candidate_session.get(key) is not None:
                    return candidate_session.get(key)
                if fallback_key:
                    return account_state.get(fallback_key)
                return None

            candidate_session_score = _session_value("trend_score", "session_trend_score")
            candidate_session_label = _session_value("trend_label", "session_trend_label")
            candidate_return = _session_value("session_return_pct", "session_return_pct")
            candidate_vwap = _session_value(
                "distance_from_vwap_pct",
                "session_distance_from_vwap_pct",
            )

            weakest = _get_weakest_position_context(account_state)

            if weakest:
                replacement_hint = "observe_only"
                reason = (
                    f"open_position_count={open_count} effective={effective_count} >= macro max_new_positions={max_new_positions}; "
                    f"candidate={symbol} session={candidate_session_label}/{candidate_session_score} "
                    f"return={candidate_return}% vwap_dist={candidate_vwap}%; "
                    f"weakest_holding={weakest.get('symbol')} "
                    f"plpc={weakest.get('unrealized_plpc'):.2f}% "
                    f"replacement_hint={replacement_hint}"
                )
            else:
                reason = (
                    f"open_position_count={open_count} effective={effective_count} >= macro max_new_positions={max_new_positions}; "
                    f"candidate={symbol} session={candidate_session_label}/{candidate_session_score} "
                    f"return={candidate_return}% vwap_dist={candidate_vwap}%; "
                    f"weakest_holding=unknown"
                )
            # Direct observe-only BUY opportunity score for macro_position_limit rejects.
            # This refreshes the candidate score after candidate_session is loaded,
            # so replacement intelligence uses live session momentum.
            if True:
                try:
                    trend = _trend_table.get(symbol) or {}
                    bias_entry = _market_bias.get(symbol) or {}
                    macro_limit_opportunity_obs = context_runtime.build_buy_opportunity_observation(
                        trend=trend,
                        bias_entry=bias_entry,
                        evaluate_buy_opportunity=evaluate_buy_opportunity,
                        required_buy_confirmations=_required_buy_confirmations,
                        log_prefix="BUY opportunity macro-limit",
                    )
                    macro_limit_buy_opportunity = macro_limit_opportunity_obs.data

                    macro_buy_score = macro_limit_buy_opportunity.get("buy_opportunity_score")
                    macro_buy_rec = macro_limit_buy_opportunity.get("buy_opportunity_recommendation")

                    # Add score/rec directly to rejection reason as a durable fallback for reporting.
                    reason = (
                        f"{reason}; buy_score={macro_buy_score}; "
                        f"buy_rec={macro_buy_rec}"
                    )
                except Exception as e:
                    logger.warning(f"BUY opportunity macro-limit scoring failed for {symbol}: {e}")

            # Portfolio rotation: if the macro position cap is full, attempt to
            # sell the weakest eligible holding before rejecting a strong candidate.
            rotated, rotation_reason, rotation_info = _try_portfolio_rotation(
                symbol,
                price,
                account_state,
                current_et,
            )

            if rotated:
                account_state["portfolio_rotation"] = rotation_info
                logger.warning(
                    f"Portfolio rotation submitted for {symbol}: {rotation_reason}; "
                    "waiting briefly for Alpaca position state to refresh"
                )

                time.sleep(2)
                refreshed_state = get_mock_account_state() or {}
                refreshed_open_count = refreshed_state.get("open_position_count", open_count)

                if refreshed_open_count < max_new_positions:
                    account_state.update(refreshed_state)
                    logger.warning(
                        f"Portfolio rotation freed a slot for {symbol}: "
                        f"open_position_count {open_count} -> {refreshed_open_count}; "
                        "continuing BUY pipeline"
                    )
                else:
                    pending_reason = (
                        f"rotation_pending: {rotation_reason}; "
                        f"open_position_count still {refreshed_open_count} >= "
                        f"macro max_new_positions={max_new_positions}; original_reason={reason}"
                    )
                    logger.warning(
                        f"Portfolio rotation pending for {symbol}: {pending_reason}"
                    )
                    if _reject_current_signal("portfolio_rotation_pending", pending_reason):
                        return
            else:
                reason = f"{reason}; rotation_not_taken={rotation_reason}"
                if _reject_current_signal("macro_position_limit", reason):
                    return

    # Trend confirmation gate: require confirmed indicator-state transitions before allowing signals through.
    if action == "buy":
        trend_obs = context_runtime.build_trend_confirmation_observation(
            current_et=current_et,
            required_buy_confirmations=_required_buy_confirmations,
            required_sell_confirmations=_required_sell_confirmations,
            is_fast_lane_buy_flip=is_fast_lane_buy_flip,
            is_fast_lane_sell_flip=is_fast_lane_sell_flip,
            market_open_minutes=MARKET_OPEN_MINUTES,
            open_momentum_fast_lane_enabled=OPEN_MOMENTUM_FAST_LANE_ENABLED,
            iex_thin_symbols=IEX_THIN_SYMBOLS,
        )
        trend = trend_obs.data
        trend_confirmation = trend_obs.confirmation
        direction = trend_obs.direction
        strength = trend_obs.strength
        consecutive_count = trend_obs.consecutive_count
        last_signal = trend_obs.last_signal
        adaptive_confirmation = trend_confirmation.get("adaptive_confirmation") or {}
        required_buy_confirmations = int(
            trend_confirmation.get("required_confirmations") or 3
        )

        if direction != "bullish" or last_signal != "buy":
            reason = (
                f"direction={direction} "
                f"last_signal={last_signal} "
                f"required={required_buy_confirmations}"
            )
            logger.info(
                f"Trend confirmation BUY observe-only for {symbol}: {reason}"
            )

        fast_lane_buy_flip = bool(trend_confirmation.get("fast_lane_buy_flip"))
        open_momentum_fast_lane = bool(
            trend_confirmation.get("open_momentum_fast_lane")
        )

        logger.info(
            f"Trend confirmation BUY for {symbol}: "
            f"required={required_buy_confirmations} "
            f"count={consecutive_count} "
            f"direction={direction} "
            f"strength={strength} "
            f"last_signal={last_signal} "
            f"flip_event={trend.get('flip_event')} "
            f"fast_lane_buy_flip={fast_lane_buy_flip} "
            f"open_momentum_fast_lane={open_momentum_fast_lane} "
            f"(elapsed={trend_confirmation.get('session_elapsed_minutes')}min "
            f"momentum={trend_confirmation.get('momentum_state')} "
            f"vol={trend_confirmation.get('volume_state')} "
            f"vol_ok={trend_confirmation.get('volume_ok')} "
            f"iex_thin={trend_confirmation.get('iex_thin')} "
            f"bias={trend_confirmation.get('bias')}) "
            f"adaptive_reason={adaptive_confirmation.get('reason')}"
        )
        if open_momentum_fast_lane and consecutive_count < required_buy_confirmations:
            logger.info(
                f"Open-momentum fast lane granted for {symbol}: "
                f"elapsed={trend_confirmation.get('session_elapsed_minutes')}min "
                f"count={consecutive_count} "
                f"momentum={trend_confirmation.get('momentum_state')} "
                f"vol={trend_confirmation.get('volume_state')} "
                f"iex_thin={trend_confirmation.get('iex_thin')}"
            )

        if not (fast_lane_buy_flip or open_momentum_fast_lane) and consecutive_count < required_buy_confirmations:
            reason = (
                f"consecutive_buy_count={consecutive_count} "
                f"< required={required_buy_confirmations} "
                f"strength={strength} "
                f"flip_event={trend.get('flip_event')} "
                f"adaptive_reason={adaptive_confirmation.get('reason')}"
            )

            if ADAPTIVE_BUY_CONFIRMATION_ENABLED:
                if _reject_approval_decision(
                    trend_confirmation_rejection(
                        reason,
                        metadata=trend_confirmation,
                    )
                ):
                    return
            else:
                logger.info(
                    f"Trend confirmation BUY observe-only for {symbol}: {reason}"
                )

    if action == "sell":
        trend_obs = context_runtime.build_trend_confirmation_observation(
            current_et=current_et,
            required_buy_confirmations=_required_buy_confirmations,
            required_sell_confirmations=_required_sell_confirmations,
            is_fast_lane_buy_flip=is_fast_lane_buy_flip,
            is_fast_lane_sell_flip=is_fast_lane_sell_flip,
            market_open_minutes=MARKET_OPEN_MINUTES,
            open_momentum_fast_lane_enabled=OPEN_MOMENTUM_FAST_LANE_ENABLED,
            iex_thin_symbols=IEX_THIN_SYMBOLS,
        )
        trend = trend_obs.data
        trend_confirmation = trend_obs.confirmation
        direction = trend_obs.direction
        strength = trend_obs.strength
        consecutive_count = trend_obs.consecutive_count
        last_signal = trend_obs.last_signal
        sell_confirmation = trend_confirmation.get("sell_confirmation") or {}
        required_sell_confirmations = int(
            trend_confirmation.get("required_confirmations") or 2
        )

        if direction != "bearish" or last_signal != "sell":
            reason = (
                f"direction={direction} "
                f"last_signal={last_signal} "
                f"required={required_sell_confirmations}"
            )
            if _reject_approval_decision(
                trend_confirmation_rejection(
                    reason,
                    metadata=trend_confirmation,
                )
            ):
                return

        fast_lane_sell_flip = bool(trend_confirmation.get("fast_lane_sell_flip"))

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
            if _reject_approval_decision(
                trend_confirmation_rejection(
                    reason,
                    metadata=trend_confirmation,
                )
            ):
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
    context_runtime.build_session_momentum_observation(
        get_latest_session_momentum=get_latest_session_momentum,
        session_momentum_is_fresh=_session_momentum_is_fresh,
    )

    if action == "sell" and existing_position:
        try:
            avg_entry = float(existing_position.get("avg_entry") or 0)
            current_price = float(existing_position.get("current_price") or price or 0)
            qty = float(existing_position.get("qty") or 0)
            if avg_entry > 0 and current_price > 0 and qty > 0:
                unrealized_pct = (current_price - avg_entry) / avg_entry * 100.0
                continuation_reason = _sell_continuation_delay_reason(
                    account_state,
                    _trend_table.get(symbol) or {},
                    unrealized_pct,
                )
                if continuation_reason:
                    if _reject_current_signal("sell_continuation_check", continuation_reason):
                        return
        except Exception as e:
            logger.warning(
                f"Sell continuation check failed for {symbol}; fail-open for SELL safety: {e}"
            )

    # Momentum check (buy signals only, fail-open — never blocks trading)
    alignment = None
    action_hint = None

    if action == "buy":
        context_runtime.hydrate_buy_live_context(only_missing=True)
        momentum = account_state.get("momentum")
        if momentum:
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
        prediction_obs = context_runtime.build_prediction_observation(
            trend=trend,
            bias_entry=bias_entry,
            evaluate_signal_quality_gate=evaluate_signal_quality_gate,
            get_cached_prediction=get_cached_prediction,
            ml_prediction_bucket=_ml_prediction_bucket,
        )
        prediction_gate = prediction_obs.data

        # ── Weak-prediction + degraded-setup gate (Phase 2, Step 6) ──────────
        # Conservative first promotion: only the weakest ML bucket (score < 45)
        # combined with an unknown/error setup triggers a heavy size cap.
        #
        # Conditions that must BOTH be true:
        #   1. ml_prediction_score < 45  (weak_below_45 bucket)
        #   2. setup is degraded         (build_snapshot failed OR setup_label is None)
        #   3. sufficient sample size    (≥ PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE)
        #      — prevents acting on near-zero-sample priors
        #
        # Mid buckets (45-50, 50-55) are observe-only; high_55_plus is a
        # tie-breaker only.  Do not change those conditions without validating
        # a full session of bucket-level P&L data first.
        _ml_score_raw = prediction_gate.get("ml_prediction_score")
        _ml_sample = int(prediction_gate.get("ml_prediction_sample_size") or 0)
        _setup_action = setup_obs.get("setup_policy_action")
        _setup_label_now = setup_obs.get("setup_label")

        _is_weak_ml_bucket = (
            _ml_score_raw is not None
            and float(_ml_score_raw) < 45
            and _ml_sample >= PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE
        )
        _is_degraded_setup_now = is_degraded_setup(setup_obs)

        if _is_weak_ml_bucket and _is_degraded_setup_now:
            _wpsg_reason = (
                f"ml_prediction_score={float(_ml_score_raw):.1f} (weak_below_45); "
                f"ml_sample_size={_ml_sample}; "
                f"setup_policy_action={_setup_action}; "
                f"setup_label={_setup_label_now!r}"
            )
            apply_size_cap(
                account_state,
                cap_pct=0.5,
                state_key="weak_prediction_setup_gate",
                payload={
                    "triggered": True,
                    "ml_score": _ml_score_raw,
                    "ml_sample_size": _ml_sample,
                    "setup_action": _setup_action,
                    "setup_label": _setup_label_now,
                    "size_cap_pct": 0.5,
                    "reason": _wpsg_reason,
                },
            )
            logger.warning(
                f"Weak-prediction + degraded-setup gate for {symbol}: "
                f"size capped at 0.5%; {_wpsg_reason}"
            )
        else:
            account_state["weak_prediction_setup_gate"] = {
                "triggered": False,
                "ml_score": _ml_score_raw,
                "ml_sample_size": _ml_sample,
                "is_weak_ml": _is_weak_ml_bucket,
                "is_degraded_setup": _is_degraded_setup_now,
            }

        # Prediction-only size cap: weak ML bucket + confident sample, even when setup
        # is known (not degraded). The stricter weak+degraded gate (0.5%) already covers
        # the degraded case; this adds a lighter cap (0.8%) when the setup is readable
        # but prediction is confidently negative.  Excluded when setup is "boost" since
        # positive setup quality takes precedence.
        _ml_confidence = prediction_gate.get("ml_prediction_confidence") or ""
        _is_confident_weak_prediction = (
            _is_weak_ml_bucket
            and _ml_confidence in ("medium", "high")
            and not _is_degraded_setup_now
            and _setup_action not in ("boost",)
        )
        if _is_confident_weak_prediction:
            _pred_only_cap = _env_float("PREDICTION_CONFIDENT_WEAK_SIZE_CAP_PCT", 0.80)
            apply_size_cap(
                account_state,
                cap_pct=_pred_only_cap,
                state_key="prediction_confident_weak_cap",
                payload={
                    "ml_score": _ml_score_raw,
                    "ml_confidence": _ml_confidence,
                    "cap_pct": _pred_only_cap,
                },
            )
            logger.info(
                f"Prediction confident-weak size cap for {symbol}: "
                f"score={_ml_score_raw} confidence={_ml_confidence} → {_pred_only_cap}%"
            )

        context_runtime.build_buy_opportunity_observation(
            trend=trend,
            bias_entry=bias_entry,
            evaluate_buy_opportunity=evaluate_buy_opportunity,
            required_buy_confirmations=_required_buy_confirmations,
            prediction_gate=prediction_gate,
            log_prefix="BUY opportunity",
        )

        prediction_decision = prediction_gate.get("prediction_decision")

        bias_override = entry_policy.live_bias_override(
            symbol=symbol,
            bias_entry=bias_entry,
            trend=trend,
            setup_obs=setup_obs,
            prediction_gate=prediction_gate,
            momentum=account_state.get("momentum") or {},
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
            if _reject_approval_decision(
                live_bias_rejection(
                    "market_bias_avoid",
                    reason,
                    metadata=bias_override,
                )
            ):
                return

        if effective_bias == "avoid_soft" and not allow_buy_from_bias:
            prediction_sample_size = int(
                prediction_gate.get("ml_prediction_sample_size")
                or (ml_prediction or {}).get("sample_size")
                or 0
            )
            reason = (
                f"effective_bias={effective_bias}; "
                f"{bias_override.get('reason')}; "
                f"prediction_sample_size={prediction_sample_size}; "
                f"min_sample_size={PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE}; "
                f"context_reason={bias_entry.get('reason','')}"
            )
            if prediction_sample_size >= PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE:
                if _reject_approval_decision(
                    live_bias_rejection(
                        "soft_avoid_prediction_gate",
                        reason,
                        metadata=bias_override,
                    )
                ):
                    return
            else:
                logger.warning(
                    f"Soft-avoid prediction gate not enforced for {symbol}: {reason}"
                )
                account_state["soft_avoid_prediction_gate_bypassed"] = True
                account_state["soft_avoid_prediction_gate_bypass_reason"] = reason

        if effective_bias == "live_override_neutral" and not allow_buy_from_bias:
            reason = (
                f"effective_bias={effective_bias}; "
                f"{bias_override.get('reason')}; "
                f"context_reason={bias_entry.get('reason','')}"
            )
            if _reject_approval_decision(
                live_bias_rejection(
                    "live_bias_downgrade",
                    reason,
                    metadata=bias_override,
                )
            ):
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

        prediction_would_block = (
            prediction_decision == "block"
            or (
                is_cash_mode()
                and prediction_decision == "watch"
            )
        )

        if PREDICTION_GATE_MODE == "warn" and prediction_would_block:
            logger.warning(
                f"Prediction gate warn-only for {symbol} BUY: "
                f"mode={EXECUTION_MODE} prediction_gate_mode={PREDICTION_GATE_MODE} "
                f"score={prediction_gate.get('prediction_score')} "
                f"decision={prediction_decision} "
                f"reason={prediction_gate.get('prediction_reason')}"
            )

        if should_block_prediction:
            reason = (
                f"mode={EXECUTION_MODE} prediction_gate_mode={PREDICTION_GATE_MODE} "
                f"score={prediction_gate.get('prediction_score')} "
                f"decision={prediction_decision} "
                f"reason={prediction_gate.get('prediction_reason')}"
            )
            if _reject_approval_decision(
                prediction_gate_rejection(reason, metadata=prediction_gate)
            ):
                return

        session_gate = entry_policy.evaluate_session_momentum_gate(
            session_momentum=account_state.get("session_momentum") or {},
            prediction_gate=prediction_gate,
            setup_obs=setup_obs,
            trend=trend,
        )
        account_state["session_momentum_gate"] = session_gate

        if session_gate.get("would_block"):
            reason = session_gate.get("reason", "session momentum gate")
            if ENFORCE_SESSION_MOMENTUM_GATE:
                if _reject_approval_decision(
                    session_momentum_rejection(reason, metadata=session_gate)
                ):
                    return
            else:
                logger.info(
                    f"Session momentum gate observe-only for {symbol} BUY: "
                    f"{session_gate.get('severity')} {reason}"
                )
        elif session_gate.get("severity") == "reversal_caution":
            logger.info(
                f"Session reversal_attempt for {symbol} BUY — caution sizing flagged: "
                f"{session_gate.get('reason')}"
            )
            account_state["session_gate_size_hint"] = "reduce"

        # Session momentum sizing — active regardless of ENFORCE_SESSION_MOMENTUM_GATE.
        # Hard blocks stay gated behind the flag; sizing caps always apply so adverse
        # momentum reduces exposure even in observe-only gate mode.
        _smg_sev = session_gate.get("severity")
        _smg_cap = None
        if _smg_sev == "soft_negative":
            _smg_cap = _env_float("SESSION_SOFT_NEGATIVE_SIZE_CAP_PCT", 0.80)
        elif _smg_sev == "reversal_caution":
            _smg_cap = _env_float("SESSION_REVERSAL_CAUTION_SIZE_CAP_PCT", 0.90)
        elif _smg_sev == "hard_negative" and not ENFORCE_SESSION_MOMENTUM_GATE:
            _smg_cap = _env_float("SESSION_HARD_NEGATIVE_SIZE_CAP_PCT", 0.65)
        if _smg_cap is not None:
            apply_size_cap(
                account_state,
                cap_pct=_smg_cap,
                state_key="session_momentum_size_cap",
                payload={"severity": _smg_sev, "cap_pct": _smg_cap},
            )
            logger.info(
                f"Session momentum size cap for {symbol}: severity={_smg_sev} → {_smg_cap}%"
            )

        # Intra-session tape degradation gate.
        # After midday, require stronger setup quality when live tape is fading/downtrend.
        if INTRA_SESSION_TAPE_DEGRADATION_ENABLED:
            try:
                _tape_now_et = datetime.now(timezone.utc).astimezone(ET)
                session_label = (account_state.get("session_momentum") or {}).get("trend_label")
                setup_score_raw = setup_obs.get("setup_score")
                setup_score = float(setup_score_raw) if setup_score_raw is not None else None

                if (
                    _tape_now_et.hour >= INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET
                    and session_label in ("fading", "downtrend")
                    and (
                        setup_score is None
                        or setup_score < INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE
                    )
                ):
                    reason = (
                        f"session_label={session_label}; "
                        f"setup_score={setup_score}; "
                        f"min_setup_score={INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE}; "
                        f"start_hour_et={INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET}"
                    )
                    account_state["intra_session_tape_degradation"] = {
                        "would_block": True,
                        "reason": reason,
                        "setup_score": setup_score,
                        "min_setup_score": INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE,
                        "session_label": session_label,
                    }
                    if _reject_current_signal("intra_session_tape_degradation", reason):
                        return
                else:
                    account_state["intra_session_tape_degradation"] = {
                        "would_block": False,
                        "setup_score": setup_score,
                        "min_setup_score": INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE,
                        "session_label": session_label,
                    }
            except Exception as e:
                logger.warning(f"Intra-session tape degradation gate skipped for {symbol}: {e}")
                account_state["intra_session_tape_degradation_error"] = str(e)

    if STRATEGY_ENGINE_MODE == "observe":
        try:
            strategy_trend = _trend_table.get(symbol) or {}
            strategy_momentum = account_state.get("momentum") or {}
            strategy_alignment = context_runtime.build_market_alignment_observation(
                symbol_market_alignment=_symbol_market_alignment,
            ).data

            strategy_result = evaluate_strategy_observe_only(
                symbol=symbol,
                action=action,
                account_state=account_state,
                trend=strategy_trend,
                momentum=strategy_momentum,
                market_alignment=strategy_alignment,
                tape=account_state.get("tape") or {},
            )
            strategy_observation = strategy_result.to_dict()
            account_state["strategy_observation"] = strategy_observation

            trader_brain = strategy_observation.get("trader_brain") or {}
            logger.info(
                f"Strategy observe for {symbol} {action.upper()}: "
                f"score={trader_brain.get('score')} "
                f"approved_by_scorer={trader_brain.get('approved_by_scorer')} "
                f"setup={trader_brain.get('setup_type')} "
                f"reason={trader_brain.get('reason')}"
            )

            # Strategy score sizing: promote trader_brain score from observe-only to
            # live sizing.  Scores below the 55 "watchlist" threshold indicate the
            # scorer sees net-negative conditions — apply a progressive cap.
            # Scores >= 55 receive no additional cap (buy_opportunity handles those).
            if action == "buy":
                _tb_score = float(trader_brain.get("score") or 0)
                _strat_cap = None
                if _tb_score < 40:
                    _strat_cap = _env_float("STRATEGY_SCORE_LOW_SIZE_CAP_PCT", 0.70)
                elif _tb_score < 55:
                    _strat_cap = _env_float("STRATEGY_SCORE_BELOW_THRESHOLD_SIZE_CAP_PCT", 0.85)
                if _strat_cap is not None:
                    apply_size_cap(
                        account_state,
                        cap_pct=_strat_cap,
                        state_key="strategy_score_size_cap",
                        payload={"score": _tb_score, "cap_pct": _strat_cap},
                    )
                    logger.info(
                        f"Strategy score size cap for {symbol}: "
                        f"score={_tb_score:.1f} → {_strat_cap}%"
                    )

        except Exception as e:
            logger.warning(f"Strategy observe failed for {symbol} {action.upper()}: {e}")

    claude_account_state = dict(account_state)

    # Pre-Claude affordability gate.
    # This is only a hard 1-share buying-power check. Macro risk and
    # buy-opportunity caps belong downstream in position sizing; using them here
    # causes false pre-Claude blocks on high-priced symbols.
    if action == "buy":
        try:
            buying_power_for_affordability = float(account_state.get("buying_power") or 0)
            signal_price_f = float(price or 0)

            if buying_power_for_affordability > 0 and signal_price_f > 0 and buying_power_for_affordability < signal_price_f:
                reason = (
                    f"buying_power ${buying_power_for_affordability:.2f} cannot buy 1 share "
                    f"at signal price ${signal_price_f:.2f}"
                )
                logger.warning(
                    f"Affordability gate blocked {symbol} BUY before Claude: {reason}"
                )
                log_rejection(
                    symbol,
                    action,
                    "affordability",
                    reason,
                    price=price,
                    account_state=account_state,
                )
                return

        except Exception as e:
            logger.warning(f"Affordability gate skipped for {symbol} BUY due to error: {e}")

    # Live-in-paper opportunity score gate.
    # This is not observe-only: low-score BUY signals are rejected before Claude.
    if action == "buy":
        opportunity = score_buy_opportunity(symbol, data, account_state)
        account_state["opportunity_score"] = opportunity
        claude_account_state["opportunity_score"] = opportunity

        strategy_memory = memory_for_signal(symbol, opportunity)
        account_state["strategy_memory"] = strategy_memory
        claude_account_state["strategy_memory"] = strategy_memory

        learned_min_score = strategy_memory.get("min_setup_score")
        if isinstance(learned_min_score, int):
            raw_score = opportunity.get("score")
            try:
                score_f = float(raw_score)
            except Exception:
                score_f = None

            # opportunity_score.py already outputs 0-100; pass through unchanged.
            normalized_score = score_f

            logger.info(
                f"STRATEGY_MEMORY {symbol} BUY: "
                f"recommendation={strategy_memory.get('recommendation')} "
                f"learned_min_score={learned_min_score} "
                f"opportunity_score={raw_score} "
                f"normalized_score={normalized_score} "
                f"reason={strategy_memory.get('reason')}"
            )

            if (
                normalized_score is not None
                and strategy_memory.get("recommendation") in ("caution", "avoid")
                and normalized_score < learned_min_score
            ):
                reason = (
                    f"strategy memory tightened {symbol}: "
                    f"recommendation={strategy_memory.get('recommendation')} "
                    f"normalized_score={normalized_score:.1f} < learned_min_score={learned_min_score}; "
                    f"{strategy_memory.get('reason')}"
                )
                logger.warning(
                    f"Strategy memory gate blocked {symbol} BUY before Claude: {reason}"
                )
                _reject_approval_decision(
                    strategy_memory_rejection(
                        reason,
                        metadata={
                            "strategy_memory": strategy_memory,
                            "opportunity_score": opportunity,
                        },
                    )
                )
                return

        logger.info(
            f"Opportunity score for {symbol} BUY: "
            f"score={opportunity.get('score')} bucket={opportunity.get('bucket')} "
            f"decision={opportunity.get('decision')} "
            f"size_multiplier={opportunity.get('size_multiplier')} "
            f"reasons={opportunity.get('reason_codes')}"
        )

        if opportunity.get("decision") == "block":
            reason = opportunity.get("summary", "opportunity score blocked setup")
            logger.warning(
                f"Opportunity score gate blocked {symbol} BUY before Claude: {reason}"
            )
            _reject_approval_decision(
                opportunity_score_rejection(reason, metadata=opportunity)
            )
            return

    intelligence_context = build_intelligence_context(
        symbol=symbol,
        action=action,
        account_state=account_state,
    )
    account_state["intelligence_context"] = intelligence_context
    claude_account_state["intelligence_context"] = intelligence_context

    summary = intelligence_context.get("summary") or {}
    logger.info(
        f"INTELLIGENCE_CONTEXT {symbol} {action.upper()}: "
        f"recommended_action={summary.get('recommended_action')} "
        f"supports={summary.get('support_count')} "
        f"risks={summary.get('risk_count')} "
        f"primary_supports={summary.get('primary_supports')} "
        f"primary_risks={summary.get('primary_risks')}"
    )

    decision_policy = evaluate_decision_policy(
        symbol=symbol,
        action=action,
        intelligence_context=intelligence_context,
        account_state=account_state,
    )
    account_state["decision_policy"] = decision_policy
    claude_account_state["decision_policy"] = decision_policy
    decision_policy_config = public_decision_policy_config()
    account_state["decision_policy_authority"] = decision_policy_config
    claude_account_state["decision_policy_authority"] = decision_policy_config

    logger.info(
        f"DECISION_POLICY {symbol} {action.upper()}: "
        f"decision={decision_policy.get('decision')} "
        f"size_multiplier={decision_policy.get('size_multiplier')} "
        f"reason={decision_policy.get('reason')} "
        f"risks={decision_policy.get('risks')} "
        f"supports={decision_policy.get('supports')}"
    )

    decision_policy_authority_enabled = decision_policy_live_authority_enabled()
    decision_policy_live_block = DECISION_POLICY_LIVE_BLOCK and decision_policy_authority_enabled
    decision_policy_live_size_down = DECISION_POLICY_LIVE_SIZE_DOWN and decision_policy_authority_enabled

    if (
        action == "buy"
        and decision_policy_live_block
        and decision_policy.get("decision") == "block"
    ):
        reason = decision_policy.get("reason", "decision policy blocked setup")
        logger.warning(
            f"Decision policy gate blocked {symbol} BUY before Claude: {reason}"
        )
        _reject_approval_decision(
            decision_policy_rejection(reason, metadata=decision_policy)
        )
        return
    elif action == "buy" and decision_policy.get("decision") == "block":
        logger.warning(
            f"Decision policy block observed but not enforced for {symbol} BUY: "
            f"authority_enabled={decision_policy_authority_enabled} "
            f"live_block_enabled={DECISION_POLICY_LIVE_BLOCK} "
            f"mode={decision_policy_config.get('authority_mode')} "
            f"reason={decision_policy.get('reason')}"
        )

    # Live decision-policy size-down:
    # This is intentionally one-way risk reduction. It can lower the max size
    # available to Claude/broker, but it cannot increase exposure.
    if (
        action == "buy"
        and decision_policy_live_size_down
        and decision_policy.get("decision") == "size_down"
    ):
        try:
            size_multiplier = float(decision_policy.get("size_multiplier") or 1.0)
        except Exception:
            size_multiplier = 1.0

        # Clamp multiplier so this can never increase size.
        size_multiplier = max(0.0, min(1.0, size_multiplier))

        current_limit = None
        for key in ("max_position_size_pct", "position_size_pct"):
            try:
                val = claude_account_state.get(key)
                if val is not None:
                    current_limit = float(val)
                    break
            except Exception:
                pass

        if current_limit is None:
            # Conservative default: normal max buy size in this project.
            current_limit = 2.0

        reduced_limit = round(current_limit * size_multiplier, 4)

        account_state["decision_policy_size_down"] = {
            "enabled": True,
            "original_position_size_pct": current_limit,
            "reduced_position_size_pct": reduced_limit,
            "size_multiplier": size_multiplier,
            "reason": decision_policy.get("reason"),
        }
        claude_account_state["decision_policy_size_down"] = account_state[
            "decision_policy_size_down"
        ]

        # Give Claude a deterministic ceiling to respect.
        claude_account_state["max_position_size_pct"] = reduced_limit
        claude_account_state["decision_policy_max_position_size_pct"] = reduced_limit

        logger.warning(
            f"DECISION_POLICY_SIZE_DOWN {symbol} BUY: "
            f"original_position_size_pct={current_limit} "
            f"size_multiplier={size_multiplier} "
            f"reduced_position_size_pct={reduced_limit} "
            f"reason={decision_policy.get('reason')}"
        )

        log_event(
            event_type="DECISION_POLICY_SIZE_DOWN",
            symbol=symbol,
            action=action,
            decision="size_down",
            severity="medium",
            reason=decision_policy.get("reason"),
            source="app.py",
            payload={
                "decision_policy": decision_policy,
                "original_position_size_pct": current_limit,
                "reduced_position_size_pct": reduced_limit,
                "size_multiplier": size_multiplier,
            },
        )
    elif action == "buy" and decision_policy.get("decision") == "size_down":
        logger.info(
            f"Decision policy size_down observed but not enforced for {symbol} BUY: "
            f"authority_enabled={decision_policy_authority_enabled} "
            f"live_size_down_enabled={DECISION_POLICY_LIVE_SIZE_DOWN} "
            f"mode={decision_policy_config.get('authority_mode')} "
            f"reason={decision_policy.get('reason')}"
        )

    if action == "buy":
        build_conviction_stack(
            action=action,
            account_state=account_state,
            ml_prediction_bucket=_ml_prediction_bucket,
            compute_dominant_limiter=sizing_policy.compute_dominant_limiter,
        )

    built_context = context_runtime.refresh(
        intelligence_context=intelligence_context,
        claude_account_state=claude_account_state,
    )
    claude_account_state = built_context.claude_account_state

    summary = built_context.summary
    logger.info(
        f"Decision context for {symbol} {action.upper()}: "
        f"setup={summary.get('setup_label')}/"
        f"{summary.get('setup_policy_action')} "
        f"prediction={summary.get('prediction_score')}/"
        f"{summary.get('prediction_decision')} "
        f"session={summary.get('session_trend_label')}/"
        f"{summary.get('session_trend_score')} "
        f"session_gate={summary.get('session_gate_severity')}/"
        f"{summary.get('session_gate_would_block')} "
        f"effective_bias={summary.get('effective_bias')}"
    )

    if action == "buy":
        logger.info(
            f"Conviction stack for {symbol} BUY: "
            f"buy_opp={account_state['conviction_stack']['buy_opportunity']} "
            f"strategy={account_state['conviction_stack']['strategy_score']:.0f} "
            f"session={account_state['conviction_stack']['session_severity']} "
            f"ml_bucket={account_state['conviction_stack']['ml_bucket']} "
            f"cap={account_state['conviction_stack']['effective_cap_pct']} "
            f"dominant={account_state['dominant_limiter']}"
        )

    weekly_perf = _weekly_symbol_performance(symbol)
    account_state["weekly_symbol_performance"] = weekly_perf
    claude_account_state["weekly_symbol_performance"] = weekly_perf

    def _medium_confidence_override_adapter(*, decision, account_state):
        return _allow_medium_confidence_momentum_override(
            symbol=symbol,
            action=action,
            decision=decision,
            account_state=account_state,
            trend=_trend_table.get(symbol) or {},
            setup_obs=account_state.get("setup_observation") or {},
        )

    approval_decision = evaluate_approval_decision(
        signal=data,
        action=action,
        claude_account_state=claude_account_state,
        evaluate_signal=evaluate_signal,
        cash_safe_mode=is_cash_safe_mode(),
        market_bias=_market_bias.get(symbol) or {},
        account_state=account_state,
        medium_confidence_override=_medium_confidence_override_adapter,
        tape_exception_enabled=TAPE_EXCEPTION_ENABLED,
    )
    decision = dict(approval_decision.claude_payload or {})

    if (approval_decision.metadata or {}).get("raw_decision", {}).get("approved") and decision.get(
        "_consistency_guard_triggered"
    ):
        logger.warning(
            f"Decision consistency guard flipped {symbol} BUY to rejected: "
            f"approved=true but reason indicated deferral"
        )

    order_result = None

    if approval_decision.category:
        logger.warning(
            f"{approval_decision.category} rejected {symbol} {action.upper()}: "
            f"{approval_decision.reason}"
        )
        log_rejection(
            symbol,
            action,
            approval_decision.category,
            approval_decision.reason,
            price=price,
            account_state=account_state,
        )
        return

    if decision.get("approved"):
        try:
            approved_reason = decision.get("reason")
            logger.info(f"APPROVED: {symbol} {action.upper()} - {approved_reason}")

            risk_multiplier = float(account_state.get("macro_risk", {}).get("risk_multiplier", 1.0))
            sizing_decision = apply_final_sizing(
                symbol=symbol,
                action=action,
                decision=decision,
                risk_multiplier=risk_multiplier,
                account_state=account_state,
                apply_buy_opportunity_sizing=lambda **kwargs: (
                    sizing_policy.apply_buy_opportunity_sizing(**kwargs, log=logger)
                ),
                log=logger,
            )
            adjusted_position_size_pct = sizing_decision.final_size_pct
            account_state["final_sizing"] = {
                "requested_size_pct": sizing_decision.requested_size_pct,
                "final_size_pct": sizing_decision.final_size_pct,
                "dominant_limiter": sizing_decision.dominant_limiter,
                "active_caps": [
                    {"source": cap.source, "cap_pct": cap.cap_pct, "reason": cap.reason}
                    for cap in sizing_decision.active_caps
                ],
                "conviction_stack": sizing_decision.conviction_stack,
            }

            execution = execute_order(
                symbol=symbol,
                action=action,
                signal=data,
                signal_price=price,
                decision=decision,
                account_state=account_state,
                position_size_pct=adjusted_position_size_pct,
                execution_mode=EXECUTION_MODE,
                pre_order_safety_check=_pre_order_safety_check,
                one_bar_confirmation_hold=_one_bar_confirmation_hold,
                make_client_order_id=_make_client_order_id,
                place_order=place_order,
                log=logger,
            )
            account_state.update(execution.account_state_updates)
            if execution.decision_updates:
                decision.update(execution.decision_updates)
            order_result = execution.order_result

            if execution.rejection_category:
                logger.warning(
                    f"{execution.rejection_category} blocked {symbol} {action.upper()}: "
                    f"{execution.rejection_reason}"
                )
                log_rejection(
                    symbol,
                    action,
                    execution.rejection_category,
                    execution.rejection_reason,
                    price=price,
                    account_state=account_state,
                )
                if dedupe_key:
                    _trade_audit_recorder().record_webhook_status(
                        dedupe_key=dedupe_key,
                        status="rejected",
                        failure_reason=execution.failure_reason,
                    )
                return

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
                    _trade_audit_recorder().record_webhook_status(
                        dedupe_key=dedupe_key,
                        status="submit_failed",
                        failure_reason=execution.failure_reason or "broker returned no order_result",
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
                _trade_audit_recorder().record_webhook_status(
                    dedupe_key=dedupe_key,
                    status="error",
                    failure_reason=f"order_path_exception: {e}",
                )
            return

    else:
        rejected_reason = decision.get("reason")
        logger.info(f"REJECTED: {symbol} {action.upper()} - {rejected_reason}")
    log_trade(data, decision, order_result, account_state=account_state)
    if dedupe_key:
        _trade_audit_recorder().record_webhook_status(
            dedupe_key=dedupe_key,
            status="processed",
        )


def _build_signal_pipeline(app_container: ApplicationContainer | None = None):
    app_container = app_container or container
    return app_container.build_signal_pipeline(
        SignalPipelineDeps(
            legacy_processor=_legacy_process_signal,
            has_open_position_db=_has_open_position_db,
            log_rejection=log_rejection,
            mark_webhook_event_status=(
                lambda dedupe_key, status, **kwargs: _trade_audit_recorder().record_webhook_status(
                    dedupe_key=dedupe_key,
                    status=status,
                    **kwargs,
                )
            ),
            logger=logger,
        )
    )


def process_signal(data):
    return _build_signal_pipeline().run(data)


def health_payload():
    account = get_account()
    return {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "account": account
    }

def _market_session():
    return market_session()

def _session_momentum_summary():
    try:
        return context_repo.session_momentum_summary()
    except Exception as e:
        logger.warning(f"session momentum summary unavailable: {e}")
        return {}


def _session_momentum_snapshot(limit=40):
    try:
        return context_repo.session_momentum_snapshot(limit=limit)
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


def _symbol_intelligence_snapshot(market_date=None):
    """Return observe-only daily prediction rows for /status visibility."""
    market_date = market_date or expected_market_context_date().isoformat()
    try:
        rows = context_repo.symbol_intelligence_rows(market_date)
        symbols = {}
        for row in rows:
            item = dict(row)
            symbol = item.pop("symbol")
            item["prediction_confidence"] = item.pop("confidence", None)
            item["prediction_reason"] = item.pop("reason", None)
            item["prediction_decision"] = "observe_only"
            symbols[symbol] = item

        return {
            "available": bool(symbols),
            "market_date": market_date,
            "symbol_count": len(symbols),
            "observe_only": True,
            "symbols": symbols,
        }
    except Exception as e:
        logger.warning(f"symbol intelligence unavailable: {e}")
        return {
            "available": False,
            "market_date": market_date,
            "observe_only": True,
            "error": str(e),
            "symbols": {},
            "symbol_count": 0,
        }


def _symbol_intelligence_for_symbol(symbol, market_date=None):
    snapshot = _symbol_intelligence_snapshot(market_date=market_date)
    return (snapshot.get("symbols") or {}).get(symbol.upper())


def status_payload():
    return build_status_payload(sys.modules[__name__])

def positions_payload():
    return build_positions_payload(sys.modules[__name__])

def debug_symbol_payload(symbol):
    return build_debug_symbol_payload(sys.modules[__name__], symbol)

app.extensions["application_container"] = container
_register_routes(app, container)


if __name__ == "__main__":
    create_app(run_startup=True).run(host="0.0.0.0", port=5000, debug=False)
