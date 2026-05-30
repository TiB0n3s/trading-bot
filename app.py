import os
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
from services import dedupe_service
from services.observability import metrics_snapshot
from services.policies import entry_policy, execution_policy, sizing_policy
from services.policy_controls import public_policy_control_config
from services.signal_pipeline import SignalPipelineDeps
from services import trend_context_service
from services import trade_audit_service
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

    RECENT_FAVORABLE_SETUP_TTL_MINUTES = 15

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
        mark_webhook_event_status=_mark_webhook_event_status,
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
            "setup_unknown_reason": None,
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
            "setup_unknown_reason": setup_policy.get("setup_unknown_reason"),
        }

    except Exception as e:
        unknown_reason = f"{type(e).__name__}:{str(e)[:200]}"
        logger.warning(
            f"setup observe-only snapshot failed for {symbol}: {unknown_reason}"
        )
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
            "setup_unknown_reason": unknown_reason,
        }

def _ml_prediction_bucket(score) -> str:
    return entry_policy.ml_prediction_bucket(score)


def _is_favorable_setup_label(setup_label: str | None) -> bool:
    return setup_label in {
        "confirmed_near_vwap_recovery",
        "near_vwap_weak_strength_followthrough",
        "oversold_weak_bounce_watch",
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


def _compute_dominant_limiter(account_state: dict) -> str:
    return sizing_policy.compute_dominant_limiter(account_state)


def _apply_buy_opportunity_sizing(
    *,
    symbol: str,
    action: str,
    base_position_size_pct: float,
    risk_multiplier: float,
    account_state: dict,
) -> float:
    return sizing_policy.apply_buy_opportunity_sizing(
        symbol=symbol,
        action=action,
        base_position_size_pct=base_position_size_pct,
        risk_multiplier=risk_multiplier,
        account_state=account_state,
        log=logger,
    )



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


def _mark_webhook_event_status(
    dedupe_key,
    status,
    order_id=None,
    client_order_id=None,
    failure_reason=None,
):
    try:
        dedupe_service.mark_webhook_event_status(
            dedupe_key,
            status,
            order_id=order_id,
            client_order_id=client_order_id,
            failure_reason=failure_reason,
        )
    except Exception as e:
        logger.warning(f"Failed to update webhook event status for {dedupe_key}: {e}")

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
    return trade_audit_service.log_trade(
        signal,
        decision,
        order,
        account_state=account_state,
        market_bias=_market_bias,
        trend_table=_trend_table,
        ml_prediction_bucket=_ml_prediction_bucket,
        log=logger,
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
    return trade_audit_service.log_rejection(
        symbol,
        action,
        category,
        reason,
        price=price,
        account_state=account_state,
        market_bias=_market_bias,
        trend_table=_trend_table,
        ml_prediction_bucket=_ml_prediction_bucket,
        log=logger,
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

def _live_bias_override(symbol, bias_entry, trend, setup_obs, prediction_gate, momentum):
    return entry_policy.live_bias_override(
        symbol, bias_entry, trend, setup_obs, prediction_gate, momentum
    )

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

def _evaluate_session_momentum_gate(session_momentum, prediction_gate, setup_obs, trend):
    return entry_policy.evaluate_session_momentum_gate(
        session_momentum, prediction_gate, setup_obs, trend
    )

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
        or _is_favorable_setup_label(setup_label)
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
    action = str(data.get("action", "")).strip().lower()
    symbol = str(data.get("symbol", "")).strip().upper()
    price = data.get("price", 0)
    logger.info(f"Processing {action.upper()} signal for {symbol} at {price}")

    account_state = get_mock_account_state()

    # Observe-only rolling multi-day / extended-hours context.
    # This is advisory data for Claude and diagnostics; it does not hard-block trades.
    try:
        rolling_ctx = rolling_symbol_context(symbol)
        if rolling_ctx:
            account_state["rolling_momentum"] = rolling_ctx
    except Exception as e:
        logger.warning(f"rolling_momentum context unavailable for {symbol}: {e}")
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
                failure_reason=format_rejection_reason(category, reason),
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

    if action == "buy":
        premarket_bias = (_market_bias.get(symbol) or {}).get("bias")
        try:
            prior_session = prior_session_context(symbol)
            if prior_session:
                account_state["prior_session"] = prior_session
        except Exception as e:
            logger.warning(f"prior_session context unavailable for {symbol}: {e}")

        try:
            tape_ctx = build_tape_context(symbol, current_price=price)
            classification = tape_ctx.get("classification") or {}
            state = tape_ctx.get("state") or {}
            bar_age_seconds = None
            if state.get("latest_bar_timestamp"):
                try:
                    latest_ts = datetime.fromisoformat(
                        str(state.get("latest_bar_timestamp")).replace("Z", "+00:00")
                    )
                    if latest_ts.tzinfo is None:
                        latest_ts = latest_ts.replace(tzinfo=timezone.utc)
                    bar_age_seconds = round(
                        (
                            datetime.now(timezone.utc)
                            - latest_ts.astimezone(timezone.utc)
                        ).total_seconds(),
                        3,
                    )
                except Exception:
                    bar_age_seconds = None
            account_state["tape"] = {
                **classification,
                "ok": tape_ctx.get("ok"),
                "bar_count": tape_ctx.get("bar_count"),
                "tape_bar_age_seconds": bar_age_seconds,
            }
        except Exception as e:
            logger.warning(f"fresh tape context unavailable for {symbol}: {e}")

        momentum = get_momentum(symbol, price, premarket_bias=premarket_bias)
        if momentum:
            account_state["momentum"] = momentum
            account_state["premarket_alignment_source"] = (
                "live_tape" if premarket_bias is not None else "missing_bias"
            )

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
            account_state["max_position_size_pct_override"] = 0.75

            logger.warning(
                f"Setup policy override for {symbol}: "
                f"{account_state['setup_policy_override']['reason']}"
            )
        else:
            if _reject_current_signal("setup_policy", reason):
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
        _current_cap = account_state.get("max_position_size_pct_override")
        account_state["max_position_size_pct_override"] = (
            min(float(_current_cap), _deg_cap) if _current_cap is not None else _deg_cap
        )
        account_state["setup_degraded"] = {
            "reason": setup_obs.get("setup_unknown_reason") or "build_snapshot_failed",
            "size_cap_pct": _deg_cap,
            "has_strong_context": _has_strong_context,
            "trend_direction": _deg_trend_dir,
            "trend_strength": _deg_trend_str,
        }
        logger.warning(
            f"Degraded setup (error) for {symbol}: size capped at {_deg_cap}%, "
            f"strong_context={_has_strong_context} "
            f"({_deg_trend_dir}/{_deg_trend_str}), "
            f"reason={setup_obs.get('setup_unknown_reason')}"
        )

    # Unrecognized label cap: taxonomy drift (new or misspelled setup_label) currently
    # passes as "neutral" action but represents unknown territory.  Apply a mild size
    # reduction so it behaves like degraded-lite rather than a known-good neutral setup.
    if action == "buy" and (setup_obs.get("setup_unknown_reason") or "").startswith("unrecognized_label:"):
        _unrecog_cap = _env_float("UNRECOGNIZED_LABEL_SIZE_CAP_PCT", 0.85)
        _existing_cap = account_state.get("max_position_size_pct_override")
        account_state["max_position_size_pct_override"] = (
            min(float(_existing_cap), _unrecog_cap) if _existing_cap is not None else _unrecog_cap
        )
        account_state["unrecognized_label_cap"] = {
            "setup_unknown_reason": setup_obs.get("setup_unknown_reason"),
            "cap_pct": _unrecog_cap,
        }
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
            broker_service.assert_position_exists(symbol)
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
                    allowed, adaptive_reason = _adaptive_churn_reentry_allowed(
                        symbol=symbol,
                        signal_price=price,
                        last_sell_price=last_sell_price,
                        account_state=account_state,
                    )

                    if allowed:
                        account_state["adaptive_churn_reentry"] = {
                            "allowed": True,
                            "price_diff_pct": round(price_diff_pct, 4),
                            "last_sell_price": last_sell_price,
                            "reason": adaptive_reason,
                        }
                        logger.warning(
                            f"Adaptive churn re-entry override for {symbol} BUY: "
                            f"signal ${price:.2f} within {price_diff_pct:.2f}% of last sell "
                            f"${last_sell_price:.2f}; {adaptive_reason}"
                        )
                    else:
                        reason = (
                            f"signal ${price:.2f} within {price_diff_pct:.2f}% of last sell "
                            f"${last_sell_price:.2f}; {adaptive_reason}"
                        )
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

    # Session trade-count gate: cap filled entries per symbol per session to reduce churn
    # on over-traded symbols (e.g. GE cycling in/out repeatedly).
    # Configurable via SESSION_MAX_TRADE_COUNT env var; defaults to 3.
    if action == "buy":
        _session_trade_limit = int(os.getenv("SESSION_MAX_TRADE_COUNT", "3"))
        filled_entries_today = _filled_buys_today(symbol)
        if filled_entries_today >= _session_trade_limit:
            reason = (
                f"filled_entries_today={filled_entries_today} >= "
                f"session_max={_session_trade_limit}"
            )
            if _reject_current_signal("session_trade_count", reason):
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

    # Observe-only BUY opportunity score before macro position-limit checks.
    # This ensures macro_position_limit rejections still get scored for replacement intelligence.
    if action == "buy" and "buy_opportunity" not in account_state:
        try:
            trend = _trend_table.get(symbol) or {}
            bias_entry = _market_bias.get(symbol) or {}
            setup_obs = account_state.get("setup_observation") or {}
            momentum = account_state.get("momentum") or {}
            recent_favorable_setup = account_state.get("recent_favorable_setup")

            adaptive_confirmation = _required_buy_confirmations(symbol, account_state)
            account_state["adaptive_buy_confirmation"] = adaptive_confirmation

            early_buy_opportunity = evaluate_buy_opportunity(
                trend=trend,
                setup_obs=setup_obs,
                bias_entry=bias_entry,
                macro_risk=account_state.get("macro_risk") or {},
                session_momentum=account_state.get("session_momentum") or {},
                momentum=momentum,
                prediction_gate={},
                recent_favorable_setup=recent_favorable_setup,
                adaptive_buy_confirmation=adaptive_confirmation,
            )
            account_state["buy_opportunity"] = early_buy_opportunity

            logger.info(
                f"BUY opportunity pre-macro for {symbol}: "
                f"score={early_buy_opportunity.get('buy_opportunity_score')} "
                f"recommendation={early_buy_opportunity.get('buy_opportunity_recommendation')} "
                f"reason={early_buy_opportunity.get('buy_opportunity_reason')}"
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
                    setup_obs = account_state.get("setup_observation") or {}
                    momentum = account_state.get("momentum") or {}
                    recent_favorable_setup = account_state.get("recent_favorable_setup")

                    adaptive_confirmation = _required_buy_confirmations(symbol, account_state)
                    account_state["adaptive_buy_confirmation"] = adaptive_confirmation

                    macro_limit_buy_opportunity = evaluate_buy_opportunity(
                        trend=trend,
                        setup_obs=setup_obs,
                        bias_entry=bias_entry,
                        macro_risk=account_state.get("macro_risk") or {},
                        session_momentum=account_state.get("session_momentum") or {},
                        momentum=momentum,
                        prediction_gate={},
                        recent_favorable_setup=recent_favorable_setup,
                        adaptive_buy_confirmation=adaptive_confirmation,
                    )
                    account_state["buy_opportunity"] = macro_limit_buy_opportunity

                    macro_buy_score = macro_limit_buy_opportunity.get("buy_opportunity_score")
                    macro_buy_rec = macro_limit_buy_opportunity.get("buy_opportunity_recommendation")

                    # Add score/rec directly to rejection reason as a durable fallback for reporting.
                    reason = (
                        f"{reason}; buy_score={macro_buy_score}; "
                        f"buy_rec={macro_buy_rec}"
                    )

                    logger.warning(
                        f"BUY opportunity macro-limit for {symbol}: "
                        f"score={macro_buy_score} "
                        f"recommendation={macro_buy_rec} "
                        f"reason={macro_limit_buy_opportunity.get('buy_opportunity_reason')}"
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
            logger.info(
                f"Trend confirmation BUY observe-only for {symbol}: {reason}"
            )

        fast_lane_buy_flip = is_fast_lane_buy_flip(
            trend,
            required_buy_confirmations=required_buy_confirmations,
        )
        account_state["fast_lane_buy_flip"] = fast_lane_buy_flip

        # Open-momentum fast lane: surge volume + accelerating momentum in the
        # first 60 minutes of session bypasses the consecutive-count gate on
        # buy-bias symbols. Pre-market research is stale by open; a confirmed
        # momentum move with institutional volume is a stronger real-time signal.
        _om_momentum = account_state.get("momentum") or {}
        _om_bias = (_market_bias.get(symbol) or {}).get("bias")
        _om_special_labels = (account_state.get("rolling_momentum") or {}).get("special_labels") or []
        session_elapsed_minutes = (
            current_et.hour * 60 + current_et.minute - MARKET_OPEN_MINUTES
        )
        _om_volume_state = _om_momentum.get("volume_state")
        # IEX captures only a fraction of consolidated volume for high-volume names;
        # requiring "surge" on IEX data would structurally exclude those symbols.
        # For IEX-thin symbols, any non-thin volume reading is sufficient — the
        # accelerating momentum and buy-bias gates remain the primary filters.
        _om_volume_ok = (
            symbol in IEX_THIN_SYMBOLS
            and _om_volume_state in ("normal", "elevated", "surge")
        ) or _om_volume_state == "surge"
        open_momentum_fast_lane = OPEN_MOMENTUM_FAST_LANE_ENABLED and (
            0 <= session_elapsed_minutes <= 60
            and _om_momentum.get("momentum_state") == "accelerating"
            and _om_volume_ok
            and _om_bias == "buy"
            and "gap_up_chase_risk" not in _om_special_labels
        )
        account_state["open_momentum_fast_lane"] = open_momentum_fast_lane

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
            f"(elapsed={session_elapsed_minutes}min momentum={_om_momentum.get('momentum_state')} "
            f"vol={_om_volume_state} vol_ok={_om_volume_ok} iex_thin={symbol in IEX_THIN_SYMBOLS} bias={_om_bias}) "
            f"adaptive_reason={adaptive_confirmation.get('reason')}"
        )
        if open_momentum_fast_lane and consecutive_count < required_buy_confirmations:
            logger.info(
                f"Open-momentum fast lane granted for {symbol}: "
                f"elapsed={session_elapsed_minutes}min count={consecutive_count} "
                f"momentum={_om_momentum.get('momentum_state')} vol={_om_volume_state} iex_thin={symbol in IEX_THIN_SYMBOLS}"
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
                if _reject_current_signal("trend_confirmation", reason):
                    return
            else:
                logger.info(
                    f"Trend confirmation BUY observe-only for {symbol}: {reason}"
                )

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
        if "prior_session" not in account_state:
            try:
                prior_session = prior_session_context(symbol)
                if prior_session:
                    account_state["prior_session"] = prior_session
            except Exception as e:
                logger.warning(f"prior_session context unavailable for {symbol}: {e}")

        if "tape" not in account_state:
            try:
                tape_ctx = build_tape_context(symbol, current_price=price)
                classification = tape_ctx.get("classification") or {}
                state = tape_ctx.get("state") or {}
                bar_age_seconds = None
                if state.get("latest_bar_timestamp"):
                    try:
                        latest_ts = datetime.fromisoformat(
                            str(state.get("latest_bar_timestamp")).replace("Z", "+00:00")
                        )
                        if latest_ts.tzinfo is None:
                            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
                        bar_age_seconds = round(
                            (
                                datetime.now(timezone.utc)
                                - latest_ts.astimezone(timezone.utc)
                            ).total_seconds(),
                            3,
                        )
                    except Exception:
                        bar_age_seconds = None
                account_state["tape"] = {
                    **classification,
                    "ok": tape_ctx.get("ok"),
                    "bar_count": tape_ctx.get("bar_count"),
                    "tape_bar_age_seconds": bar_age_seconds,
                }
            except Exception as e:
                logger.warning(f"fresh tape context unavailable for {symbol}: {e}")

        premarket_bias = bias_entry.get("bias")
        momentum = account_state.get("momentum")
        if not momentum:
            momentum = get_momentum(symbol, price, premarket_bias=premarket_bias)
        if momentum:
            account_state["momentum"] = momentum
            # Record source so decision_snapshots can flag when bias was absent.
            account_state["premarket_alignment_source"] = (
                "live_tape" if premarket_bias is not None else "missing_bias"
            )

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
        ml_prediction = get_cached_prediction(symbol)

        prediction_gate = evaluate_signal_quality_gate(
            trend_direction=trend.get("direction"),
            trend_strength=trend.get("strength"),
            market_bias=bias_entry.get("bias"),
            setup_label=setup_obs.get("setup_label"),
            setup_policy_action=setup_obs.get("setup_policy_action"),
            momentum_direction=momentum.get("direction"),
            momentum_pct=momentum.get("momentum_pct"),
            consecutive_buy_count=trend.get("consecutive_count") or 0,
            recent_favorable_setup=recent_favorable_setup,
            ml_prediction=ml_prediction,
        )

        account_state["prediction_gate"] = prediction_gate
        account_state["ml_prediction"] = ml_prediction or {}

        logger.info(
            f"Signal quality gate for {symbol} BUY: "
            f"score={prediction_gate.get('prediction_score')} "
            f"decision={prediction_gate.get('prediction_decision')} "
            f"reason={prediction_gate.get('prediction_reason')} "
            f"ml_score={prediction_gate.get('ml_prediction_score')} "
            f"ml_compare={prediction_gate.get('ml_prediction_compare_decision')} "
            f"ml_agrees={prediction_gate.get('ml_prediction_agrees_with_gate')}"
        )

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
        _is_degraded_setup_now = (
            _setup_action == "error"
            or (setup_obs.get("setup_unknown_reason") or "").startswith("unrecognized_label:")
            or (
                _setup_label_now is None
                and _setup_action not in ("not_applicable",)
            )
        )

        if _is_weak_ml_bucket and _is_degraded_setup_now:
            _wpsg_reason = (
                f"ml_prediction_score={float(_ml_score_raw):.1f} (weak_below_45); "
                f"ml_sample_size={_ml_sample}; "
                f"setup_policy_action={_setup_action}; "
                f"setup_label={_setup_label_now!r}"
            )
            _existing_cap = account_state.get("max_position_size_pct_override")
            account_state["max_position_size_pct_override"] = (
                min(float(_existing_cap), 0.5) if _existing_cap is not None else 0.5
            )
            account_state["weak_prediction_setup_gate"] = {
                "triggered": True,
                "ml_score": _ml_score_raw,
                "ml_sample_size": _ml_sample,
                "setup_action": _setup_action,
                "setup_label": _setup_label_now,
                "size_cap_pct": 0.5,
                "reason": _wpsg_reason,
            }
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
            _existing = account_state.get("max_position_size_pct_override")
            account_state["max_position_size_pct_override"] = (
                min(float(_existing), _pred_only_cap) if _existing is not None else _pred_only_cap
            )
            account_state["prediction_confident_weak_cap"] = {
                "ml_score": _ml_score_raw,
                "ml_confidence": _ml_confidence,
                "cap_pct": _pred_only_cap,
            }
            logger.info(
                f"Prediction confident-weak size cap for {symbol}: "
                f"score={_ml_score_raw} confidence={_ml_confidence} → {_pred_only_cap}%"
            )

        buy_opportunity = evaluate_buy_opportunity(
            trend=trend,
            setup_obs=setup_obs,
            bias_entry=bias_entry,
            macro_risk=account_state.get("macro_risk") or {},
            session_momentum=account_state.get("session_momentum") or {},
            momentum=momentum,
            prediction_gate=prediction_gate,
            recent_favorable_setup=recent_favorable_setup,
            adaptive_buy_confirmation=account_state.get("adaptive_buy_confirmation") or {},
        )
        account_state["buy_opportunity"] = buy_opportunity

        logger.info(
            f"BUY opportunity for {symbol}: "
            f"score={buy_opportunity.get('buy_opportunity_score')} "
            f"recommendation={buy_opportunity.get('buy_opportunity_recommendation')} "
            f"reason={buy_opportunity.get('buy_opportunity_reason')}"
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
                if _reject_current_signal("soft_avoid_prediction_gate", reason):
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
            _existing = account_state.get("max_position_size_pct_override")
            account_state["max_position_size_pct_override"] = (
                min(float(_existing), _smg_cap) if _existing is not None else _smg_cap
            )
            account_state["session_momentum_size_cap"] = {
                "severity": _smg_sev, "cap_pct": _smg_cap,
            }
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
            strategy_alignment = account_state.get("market_alignment") or {}

            if not strategy_alignment and action == "buy":
                try:
                    strategy_alignment = _symbol_market_alignment(symbol)
                except Exception:
                    strategy_alignment = {}

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
                    _existing = account_state.get("max_position_size_pct_override")
                    account_state["max_position_size_pct_override"] = (
                        min(float(_existing), _strat_cap) if _existing is not None else _strat_cap
                    )
                    account_state["strategy_score_size_cap"] = {
                        "score": _tb_score, "cap_pct": _strat_cap,
                    }
                    logger.info(
                        f"Strategy score size cap for {symbol}: "
                        f"score={_tb_score:.1f} → {_strat_cap}%"
                    )

        except Exception as e:
            logger.warning(f"Strategy observe failed for {symbol} {action.upper()}: {e}")

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

    # Claude-safe account state:
    # Keep observe-only diagnostics in /status, DB context, and reports,
    # but do not send them to Claude where they can behave like live gates.
    # Raw gate objects (adaptive_buy_confirmation, market_alignment) are stripped
    # and replaced with a lightweight summary so Claude has the key facts without
    # being exposed to internal gate state that could create implicit live gates.
    claude_account_state = dict(account_state)
    _ac_raw = account_state.get("adaptive_buy_confirmation") or {}
    _ma_raw = account_state.get("market_alignment") or {}
    claude_account_state.pop("adaptive_buy_confirmation", None)
    claude_account_state.pop("adaptive_buy_confirmation_error", None)
    claude_account_state.pop("market_alignment", None)
    claude_account_state.pop("market_alignment_error", None)
    claude_account_state["market_context_summary"] = {
        "required_confirmations": _ac_raw.get("required_buy_confirmations"),
        "confirmation_reasons": _ac_raw.get("reasons"),
        "market_aligned": _ma_raw.get("aligned_for_buy"),
        "alignment_reason": _ma_raw.get("reason"),
    }

    # Conviction stack diagnostic: single dict summarising which signals are active
    # and what effective size cap results.  Logged for every BUY decision path.
    if action == "buy":
        _cs_ml_raw = (account_state.get("prediction_gate") or {}).get("ml_prediction_score")
        account_state["conviction_stack"] = {
            "buy_opportunity": (account_state.get("buy_opportunity") or {}).get("buy_opportunity_recommendation"),
            "strategy_score": float(
                (account_state.get("strategy_observation") or {}).get("trader_brain", {}).get("score") or 0
            ),
            "session_severity": (account_state.get("session_momentum_gate") or {}).get("severity"),
            "ml_bucket": _ml_prediction_bucket(_cs_ml_raw),
            "effective_cap_pct": account_state.get("max_position_size_pct_override"),
        }
        account_state["dominant_limiter"] = _compute_dominant_limiter(account_state)
        logger.info(
            f"Conviction stack for {symbol} BUY: "
            f"buy_opp={account_state['conviction_stack']['buy_opportunity']} "
            f"strategy={account_state['conviction_stack']['strategy_score']:.0f} "
            f"session={account_state['conviction_stack']['session_severity']} "
            f"ml_bucket={account_state['conviction_stack']['ml_bucket']} "
            f"cap={account_state['conviction_stack']['effective_cap_pct']} "
            f"dominant={account_state['dominant_limiter']}"
        )

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
                log_rejection(
                    symbol,
                    action,
                    "strategy_memory",
                    reason,
                    price=price,
                    account_state=account_state,
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
            log_rejection(
                symbol,
                action,
                "opportunity_score",
                reason,
                price=price,
                account_state=account_state,
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
        log_rejection(
            symbol,
            action,
            "decision_policy",
            reason,
            price=price,
            account_state=account_state,
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

    weekly_perf = _weekly_symbol_performance(symbol)
    account_state["weekly_symbol_performance"] = weekly_perf
    claude_account_state["weekly_symbol_performance"] = weekly_perf

    decision = evaluate_signal(data, claude_account_state)

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

    # Neutral-bias confidence gate: neutral market-bias signals have historically poor
    # expectancy (-$1.41/trade vs +$1.63 for buy-bias). Require high confidence to proceed.
    # Exception (TAPE_EXCEPTION_ENABLED): accelerating momentum + elevated/surge volume +
    # clean_momentum tape overrides a stale neutral pre-market classification. Pre-market
    # research runs hours before the open; by mid-session a confirmed ETF momentum move
    # with clean tape is a stronger real-time signal than the stale neutral classification.
    if action == "buy" and decision.get("confidence") != "high":
        bias_entry = _market_bias.get(symbol) or {}
        if bias_entry.get("bias") == "neutral":
            momentum_ctx = (account_state or {}).get("momentum") or {}
            tape = (account_state or {}).get("tape") or {}
            tape_label = tape.get("label")
            vol_state = momentum_ctx.get("volume_state")
            momentum_state = momentum_ctx.get("momentum_state")
            tape_exception = TAPE_EXCEPTION_ENABLED and (
                momentum_state == "accelerating"
                and vol_state in ("elevated", "surge")
                and tape_label == "clean_momentum"
            )
            if tape_exception:
                logger.info(
                    f"Neutral-bias gate exception granted for {symbol}: "
                    f"momentum_state={momentum_state} vol={vol_state} tape={tape_label} "
                    f"confidence={decision.get('confidence')}"
                )
            else:
                conf = decision.get("confidence")
                medium_ok, medium_reason = _allow_medium_confidence_momentum_override(
                    symbol=symbol,
                    action=action,
                    decision=decision,
                    account_state=account_state,
                    trend=trend,
                    setup_obs=setup_obs,
                )
                if medium_ok:
                    logger.warning(
                        f"Neutral-bias confidence gate override granted for {symbol}: "
                        f"confidence={conf}; {medium_reason}"
                    )
                    account_state["confidence_gate_medium_override"] = {
                        "gate": "neutral_bias",
                        "reason": medium_reason,
                    }
                else:
                    logger.warning(
                        f"Neutral-bias confidence gate rejected {symbol} BUY: confidence={conf} "
                        f"(momentum_state={momentum_state} vol={vol_state} tape={tape_label} "
                        f"tape_exception_enabled={TAPE_EXCEPTION_ENABLED}; "
                        f"override_reject={medium_reason})"
                    )
                    log_rejection(
                        symbol, action, "confidence_gate",
                        f"neutral_bias requires confidence=high; got {conf} "
                        f"(reason: {decision.get('reason', '')})",
                        price=price, account_state=account_state,
                    )
                    return

    # Conditional entry quality gate: conditional setups have 17% win rate and -$1.41
    # expectancy. Require high confidence before allowing an entry.
    if action == "buy" and decision.get("confidence") != "high":
        bias_entry = _market_bias.get(symbol) or {}
        if bias_entry.get("entry_quality") == "conditional":
            conf = decision.get("confidence")
            medium_ok, medium_reason = _allow_medium_confidence_momentum_override(
                symbol=symbol,
                action=action,
                decision=decision,
                account_state=account_state,
                trend=trend,
                setup_obs=setup_obs,
            )
            if medium_ok:
                logger.warning(
                    f"Conditional entry quality gate override granted for {symbol}: "
                    f"confidence={conf}; {medium_reason}"
                )
                account_state["confidence_gate_medium_override"] = {
                    "gate": "conditional_entry_quality",
                    "reason": medium_reason,
                }
            else:
                logger.warning(
                    f"Conditional entry quality gate rejected {symbol} BUY: "
                    f"confidence={conf}; override_reject={medium_reason}"
                )
                log_rejection(
                    symbol, action, "confidence_gate",
                    f"conditional_entry_quality requires confidence=high; got {conf} "
                    f"(reason: {decision.get('reason', '')})",
                    price=price, account_state=account_state,
                )
                return

    if decision.get("approved"):
        try:
            approved_reason = decision.get("reason")
            logger.info(f"APPROVED: {symbol} {action.upper()} - {approved_reason}")

            risk_multiplier = float(account_state.get("macro_risk", {}).get("risk_multiplier", 1.0))
            adjusted_position_size_pct = float(decision.get("position_size_pct", 1.0) or 1.0) * risk_multiplier

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

                if action == "buy":
                    one_bar_ok, one_bar_reason = _one_bar_confirmation_hold(
                        symbol=symbol,
                        signal_price=price,
                        account_state=account_state,
                    )
                    account_state["one_bar_confirmation_hold"] = {
                        "allowed": one_bar_ok,
                        "reason": one_bar_reason,
                    }

                    if not one_bar_ok:
                        logger.warning(
                            f"One-bar confirmation hold blocked {symbol} BUY: "
                            f"{one_bar_reason}"
                        )
                        log_rejection(
                            symbol,
                            action,
                            "one_bar_confirmation_hold",
                            one_bar_reason,
                            price=price,
                            account_state=account_state,
                        )
                        if dedupe_key:
                            _mark_webhook_event_status(
                                dedupe_key,
                                "rejected",
                                failure_reason=f"one_bar_confirmation_hold: {one_bar_reason}",
                            )
                        return

                    logger.info(
                        f"One-bar confirmation hold passed for {symbol} BUY: "
                        f"{one_bar_reason}"
                    )

                client_order_id = _make_client_order_id(symbol, action, data)
                logger.info(
                    f"BROKER SUBMIT START: {symbol} {action.upper()} "
                    f"client_order_id={client_order_id}"
                )

                if action == "buy" and decision.get("approved"):
                    max_size_override = account_state.get("max_position_size_pct_override")
                    if max_size_override is not None:
                        try:
                            original_size = float(decision.get("position_size_pct") or 0)
                            capped_size = min(original_size, float(max_size_override))

                            if capped_size < original_size:
                                logger.warning(
                                    f"Position size capped for {symbol}: "
                                    f"{original_size:.2f}% -> {capped_size:.2f}% "
                                    f"due to setup_policy_override"
                                )
                                decision["position_size_pct"] = capped_size
                        except Exception as e:
                            logger.warning(f"Failed to apply size override for {symbol}: {e}")

                adjusted_position_size_pct = _apply_buy_opportunity_sizing(
                    symbol=symbol,
                    action=action,
                    base_position_size_pct=decision.get("position_size_pct", 1.0),
                    risk_multiplier=risk_multiplier,
                    account_state=account_state,
                )

                order_result = place_order(
                    symbol=symbol,
                    action=action,
                    position_size_pct=adjusted_position_size_pct,
                    stop_loss_pct=decision.get("stop_loss_pct", 1.75),
                    take_profit_pct=0,  # TP disabled; position_manager owns exits
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
                decision["approved"] = False
                decision["reason"] = "order_submission_failed: broker returned no order_result"
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


def _build_signal_pipeline(app_container: ApplicationContainer | None = None):
    app_container = app_container or container
    return app_container.build_signal_pipeline(
        SignalPipelineDeps(
            legacy_processor=_legacy_process_signal,
            has_open_position_db=_has_open_position_db,
            log_rejection=log_rejection,
            mark_webhook_event_status=_mark_webhook_event_status,
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
    result = {
        "timestamp": datetime.now().isoformat(),
        "execution_mode": EXECUTION_MODE,
        "runtime_config": public_runtime_config(),
    }
    result["session_momentum_gate_enabled"] = ENFORCE_SESSION_MOMENTUM_GATE
    result["prediction_gate_mode"] = PREDICTION_GATE_MODE
    result["prediction_gate_thresholds"] = PREDICTION_GATE_THRESHOLDS
    result["prediction_gate_name"] = "deterministic_signal_quality_gate"
    result["ml_prediction_cache"] = prediction_cache_status()
    result["decision_policy"] = public_decision_policy_config()
    result["policy_controls"] = public_policy_control_config()
    result["runtime_metrics"] = metrics_snapshot()
    result["strategy_engine_mode"] = STRATEGY_ENGINE_MODE
    result["execution_policy_mode"] = os.getenv("EXECUTION_POLICY_MODE", "compare").strip().lower()
    result["intra_session_tape_degradation_enabled"] = INTRA_SESSION_TAPE_DEGRADATION_ENABLED
    result["one_bar_confirmation_hold_enabled"] = ONE_BAR_CONFIRMATION_HOLD_ENABLED
    result["prediction_soft_avoid_min_sample_size"] = PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE
    result["macro_position_count_floor"] = MACRO_POSITION_COUNT_FLOOR
    result["tape_exception_enabled"] = TAPE_EXCEPTION_ENABLED
    result["open_momentum_fast_lane_enabled"] = OPEN_MOMENTUM_FAST_LANE_ENABLED
    result["risk_policy_mode"] = RISK_POLICY_MODE
    result["portfolio_rotation"] = {
        "mode": os.getenv("PORTFOLIO_REPLACEMENT_MODE", "observe_only").strip().lower(),
        "live_sells": os.getenv("PORTFOLIO_REPLACEMENT_LIVE_SELLS", "false").strip().lower()
        in ("1", "true", "yes", "on"),
        "require_replace_now": os.getenv(
            "PORTFOLIO_REPLACEMENT_REQUIRE_REPLACE_NOW", "true"
        ).strip().lower() in ("1", "true", "yes", "on"),
        "min_candidate_score": float(os.getenv("PORTFOLIO_REPLACEMENT_MIN_CANDIDATE_SCORE", "120")),
        "min_buy_score": float(os.getenv("PORTFOLIO_REPLACEMENT_MIN_BUY_SCORE", "15")),
        "weak_holding_plpc": float(os.getenv("PORTFOLIO_REPLACEMENT_WEAK_HOLDING_PLPC", "-1.00")),
        "runtime_effect": "live_sell_path" if os.getenv(
            "PORTFOLIO_REPLACEMENT_LIVE_SELLS", "false"
        ).strip().lower() in ("1", "true", "yes", "on") else "observe_only",
    }
    result["alerts"] = alert_config_public()
    result["session_momentum_summary"] = _session_momentum_summary()
    result["session_momentum"] = _session_momentum_snapshot()
    result["symbol_intelligence"] = _symbol_intelligence_snapshot()
    result["policy_artifacts"] = policy_artifact_status(Path(__file__).parent)
    
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

    # Observe-only rolling multi-day momentum context
    try:
        result["rolling_momentum"] = rolling_summary()
    except Exception as e:
        logger.error(f"/status rolling_momentum error: {e}")

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

    # Read-only ledger/DB summary.
    try:
        result["ledger_summary"] = ledger_summary()
    except Exception as e:
        result["ledger_summary_error"] = str(e)

    # Detailed positions (now with trend, market_bias, and exposure-cap signals)
    symbols_at_cap = []
    try:
        alpaca_positions = broker_service.list_positions()
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
            for p in broker_service.list_positions():
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

    # Read-only risk package telemetry.
    # This does not replace or weaken live inline risk gates.
    if RISK_POLICY_MODE == "compare":
        try:
            macro_live = result.get("macro_risk") or get_macro_risk(Path(__file__).parent)
            positions_for_risk = result.get("positions") or []
            account_for_risk = result.get("account") or {}

            result["risk_account_snapshot"] = account_risk_snapshot(
                account=account_for_risk,
                positions=positions_for_risk,
                daily_pnl_pct=account_for_risk.get("daily_pnl_pct"),
                max_positions=int(macro_live.get("max_new_positions") or 8),
            )

            guard_policy = live_guard_policy(os.environ)
            allowed, guard_reason = live_order_allowed(guard_policy)
            result["risk_live_guard_policy"] = {
                **guard_policy,
                "live_order_allowed": allowed,
                "live_order_reason": guard_reason,
            }

            ctx_path = Path(__file__).parent / "market_context.json"
            if ctx_path.exists():
                ctx = json.loads(ctx_path.read_text())
                macro_policy_compare = policy_from_market_context(ctx)
                result["risk_macro_policy_compare"] = {
                    "package_policy": macro_policy_compare,
                    "live_macro_risk": macro_live,
                    "matches_live": (
                        macro_policy_compare.get("macro_regime") == macro_live.get("macro_regime")
                        and macro_policy_compare.get("risk_multiplier") == macro_live.get("risk_multiplier")
                        and macro_policy_compare.get("max_new_positions") == macro_live.get("max_new_positions")
                        and macro_policy_compare.get("block_new_buys") == macro_live.get("block_new_buys")
                    ),
                }
            else:
                result["risk_macro_policy_compare"] = {
                    "error": "market_context.json missing",
                    "live_macro_risk": macro_live,
                }
        except Exception as e:
            result["risk_policy_error"] = str(e)

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
            cd_rows = cooldown_repo.cooldown_rows()
            cs_rows = cooldown_repo.recent_sell_rows()
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
            for sym, ts_str, *_ in cs_rows:
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
        result["today_signals"] = trades_repo.today_signal_counts()
    except Exception as e:
        logger.error(f"/status signal counts error: {e}")

    try:
        result["intelligence"] = get_intelligence_snapshot()
    except Exception as e:
        result["intelligence"] = {
            "available": False,
            "error": str(e),
        }

    return result


def positions_payload():
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
        for p in broker_service.list_positions():
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
                    "unrealized_plpc": round(unrealized_pl_pct, 3),
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
        "max_positions": MAX_OPEN_POSITIONS,
        "total_unrealized_pl": round(total_unrealized, 2),
        "account_balance": balance,
        "daily_pnl_pct": daily_pnl_pct,
        "market_context_date": market_context_date,
        "macro_sentiment": macro_sentiment,
    }
    result["positions"] = sorted(positions_list, key=lambda x: -(x.get("market_value") or 0))
    try:
        for position in result.get("positions", []):
            symbol = position.get("symbol")
            position["intelligence"] = get_position_intelligence(symbol)
    except Exception as e:
        result["position_intelligence_error"] = str(e)

    return result


def debug_symbol_payload(symbol):
    symbol = symbol.upper()
    if symbol not in APPROVED_SYMBOLS:
        return {
            "error": "symbol not approved",
            "symbol": symbol,
            "approved_symbols": sorted(APPROVED_SYMBOLS),
        }, 400

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

    # Observe-only rolling multi-day momentum context
    try:
        result["rolling_momentum"] = rolling_symbol_context(symbol)
    except Exception as e:
        result["rolling_momentum_error"] = str(e)

    # Observe-only market alignment
    try:
        result["market_alignment"] = _symbol_market_alignment(symbol)
    except Exception as e:
        result["market_alignment_error"] = str(e)

    # Observe-only daily prediction intelligence
    try:
        result["symbol_intelligence"] = _symbol_intelligence_for_symbol(symbol)
    except Exception as e:
        result["symbol_intelligence_error"] = str(e)

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

    return result, 200


app.extensions["application_container"] = container
_register_routes(app, container)


if __name__ == "__main__":
    create_app(run_startup=True).run(host="0.0.0.0", port=5000, debug=False)
