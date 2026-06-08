"""Flask composition root for the trading bot.

This module should stay limited to Flask app creation, startup entry points,
container selection, route registration, and the public `process_signal()`
compatibility wrapper. Trading behavior belongs in services, policies,
repositories, and infrastructure adapters.
"""

import hashlib
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytz
from flask import Flask, abort

from alerts import alert_config_public as alert_config_public  # noqa: F401
from bot_events import log_event as log_event  # noqa: F401
from data_layer.ledger import ledger_summary as ledger_summary  # noqa: F401
from decision_context import build_intelligence_context as build_intelligence_context  # noqa: F401
from decision_engine import evaluate_signal as evaluate_signal  # noqa: F401
from decision_engine import get_mock_account_state as get_mock_account_state  # noqa: F401
from decision_policy import evaluate_decision_policy as evaluate_decision_policy  # noqa: F401
from decision_thresholds import (
    PREDICTION_GATE_THRESHOLDS as PREDICTION_GATE_THRESHOLDS,  # noqa: F401
)
from exceptions import ValidationError as ValidationError  # noqa: F401
from indicator_state import (
    is_fast_lane_buy_flip as is_fast_lane_buy_flip,  # noqa: F401
)
from indicator_state import (
    is_fast_lane_sell_flip as is_fast_lane_sell_flip,  # noqa: F401
)
from intelligence_snapshot import (
    get_intelligence_snapshot as get_intelligence_snapshot,  # noqa: F401
)
from live_features import build_snapshot
from macro_risk import get_macro_risk as _legacy_get_macro_risk
from market_time import expected_market_context_date, is_market_hours, market_session, now_et
from opportunity_score import score_buy_opportunity as score_buy_opportunity  # noqa: F401
from policy_artifacts import policy_artifact_status as policy_artifact_status  # noqa: F401
from position_intelligence import (
    get_position_intelligence as get_position_intelligence,  # noqa: F401
)
from prediction_cache import (
    get_cached_prediction,
)
from prediction_cache import (
    prediction_cache_status as prediction_cache_status,  # noqa: F401
)
from prior_session_context import prior_session_context
from repositories import context_repo, cooldown_repo, trades_repo
from risk.account_risk import account_risk_snapshot as account_risk_snapshot  # noqa: F401
from risk.live_guards import live_guard_policy as live_guard_policy  # noqa: F401
from risk.live_guards import live_order_allowed as live_order_allowed  # noqa: F401
from risk.macro_policy import policy_from_market_context as policy_from_market_context  # noqa: F401
from rolling_context import rolling_summary as rolling_summary  # noqa: F401
from rolling_context import rolling_symbol_context
from runtime_config import (
    CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY,
    CASH_SAFE_MAX_OPEN_POSITIONS,
    CASH_SAFE_MAX_ORDER_DOLLARS,
    CASH_SAFE_SYMBOLS,
    DECISION_POLICY_LIVE_BLOCK,
    DECISION_POLICY_LIVE_SIZE_DOWN,
    EXECUTION_MODE,
    LIVE_TRADING_ENABLED,
    MAX_LIVE_ORDER_DOLLARS,
    decision_policy_live_authority_enabled,
    is_cash_mode,
    is_cash_safe_mode,
    public_decision_policy_config,
    public_runtime_config,
)
from runtime_config import (
    public_ml_authority_config as public_ml_authority_config,  # noqa: F401
)
from services import dedupe_service, trade_audit_service
from services.container import ApplicationContainer
from services.context_builder import (
    ContextAssemblyDeps,
)
from services.context_builder import (
    apply_market_bias_context as context_builder_apply_market_bias_context,
)
from services.context_builder import (
    build_signal_context_runtime as build_signal_context_runtime,  # noqa: F401
)
from services.execution_adapters import ExecutionAdapterService
from services.execution_service import execute_order as execute_order  # noqa: F401
from services.market_context_service import MarketContextService
from services.momentum_service import MomentumService
from services.observability import metrics_snapshot as metrics_snapshot  # noqa: F401
from services.policies import entry_policy
from services.policies import sizing_policy as sizing_policy  # noqa: F401
from services.policy_controls import (
    public_policy_control_config as public_policy_control_config,  # noqa: F401
)
from services.portfolio_rotation_service import PortfolioRotationService
from services.preflight_service import (
    PreflightDeps,
    PreflightService,
    normalize_signal_identity,
)
from services.regime_observation_service import build_default_regime_observation_service
from services.setup_context_service import (
    SetupContextDeps,
    is_degraded_setup,
    is_favorable_setup_label,
    is_unrecognized_setup_label,
)
from services.setup_engine_service import build_default_setup_engine_service
from services.signal_models import SignalRuntimeState
from services.sizing_service import apply_final_sizing as apply_final_sizing  # noqa: F401
from services.sizing_service import apply_size_cap
from services.sizing_service import build_conviction_stack as build_conviction_stack  # noqa: F401
from services.symbol_override_service import SymbolOverrideService
from services.trend_state_service import TrendStateService
from session_momentum import (
    get_latest_session_momentum,
)
from setup_policy import evaluate_setup_policy
from strategy.strategy_engine import evaluate_strategy_observe_only
from strategy_constants import (
    ADAPTIVE_BUY_CONFIRMATION_ENABLED,
    DAILY_LOSS_LIMIT_PCT,
    MARKET_CLOSE_MINUTES,
    MARKET_OPEN_MINUTES,
    MAX_BUYS_PER_SYMBOL_PER_DAY,
    MAX_OPEN_POSITIONS,
    SYMBOL_MARKET_ALIGNMENT,
    WEBHOOK_DEDUPE_SECONDS,
)
from strategy_memory import memory_for_signal as memory_for_signal  # noqa: F401
from symbols_config import (
    APPROVED_SYMBOLS,
    CLUSTER_EXPOSURE_LIMITS,
    CORRELATION_CLUSTERS,
    IEX_THIN_SYMBOLS,
    SYMBOL_MAX_SPREAD_PCT,
)
from symbols_config import PRICE_RANGES as PRICE_RANGES  # noqa: F401
from trading_bot.config.runtime import load_runtime_settings
from trading_bot.runtime.startup import run_runtime_startup_tasks
from trading_bot.web.app_factory import create_runtime_flask_app

_RUNTIME_COMPAT_EXPORTS = (
    ADAPTIVE_BUY_CONFIRMATION_ENABLED,
    CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY,
    CASH_SAFE_MAX_OPEN_POSITIONS,
    CASH_SAFE_MAX_ORDER_DOLLARS,
    CASH_SAFE_SYMBOLS,
    DECISION_POLICY_LIVE_BLOCK,
    DECISION_POLICY_LIVE_SIZE_DOWN,
    LIVE_TRADING_ENABLED,
    MARKET_CLOSE_MINUTES,
    MARKET_OPEN_MINUTES,
    MAX_LIVE_ORDER_DOLLARS,
    MAX_OPEN_POSITIONS,
    PREDICTION_GATE_THRESHOLDS,
    PRICE_RANGES,
    ValidationError,
    account_risk_snapshot,
    alert_config_public,
    apply_final_sizing,
    build_signal_context_runtime,
    build_conviction_stack,
    build_intelligence_context,
    decision_policy_live_authority_enabled,
    evaluate_decision_policy,
    evaluate_signal,
    execute_order,
    get_cached_prediction,
    get_intelligence_snapshot,
    get_mock_account_state,
    get_position_intelligence,
    is_cash_mode,
    is_cash_safe_mode,
    is_degraded_setup,
    is_fast_lane_buy_flip,
    is_fast_lane_sell_flip,
    is_unrecognized_setup_label,
    ledger_summary,
    live_guard_policy,
    live_order_allowed,
    log_event,
    market_session,
    memory_for_signal,
    metrics_snapshot,
    normalize_signal_identity,
    policy_artifact_status,
    policy_from_market_context,
    prediction_cache_status,
    public_decision_policy_config,
    public_ml_authority_config,
    public_policy_control_config,
    public_runtime_config,
    rolling_summary,
    score_buy_opportunity,
    sizing_policy,
    time,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("trading_bot.log"), logging.StreamHandler()],
)
ET = ZoneInfo("America/New_York")
et = pytz.timezone("America/New_York")
logger = logging.getLogger(__name__)

container = ApplicationContainer.create_default(
    logger=logger,
    signal_executor_factory=lambda: _get_signal_executor(),
)

# Compatibility aliases while service orchestration is wired.
broker_service = container.broker_service
market_data_service = container.market_data_service
tape_service = container.tape_service

DB_PATH = Path(__file__).parent / "trades.db"
_START_TIME = datetime.now(timezone.utc)
_runtime_settings = load_runtime_settings(
    env_get=os.environ.get,
    execution_mode=EXECUTION_MODE,
    warn=logger.warning,
)
IS_PAPER_MODE = _runtime_settings.IS_PAPER_MODE
ENFORCE_SETUP_POLICY_BLOCKS = _runtime_settings.ENFORCE_SETUP_POLICY_BLOCKS
SIGNAL_TTL_SECONDS = _runtime_settings.SIGNAL_TTL_SECONDS
PREDICTION_GATE_MODE = _runtime_settings.PREDICTION_GATE_MODE
PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE = _runtime_settings.PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE
INTRA_SESSION_TAPE_DEGRADATION_ENABLED = _runtime_settings.INTRA_SESSION_TAPE_DEGRADATION_ENABLED
INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET = (
    _runtime_settings.INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET
)
INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE = (
    _runtime_settings.INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE
)
ONE_BAR_CONFIRMATION_HOLD_ENABLED = _runtime_settings.ONE_BAR_CONFIRMATION_HOLD_ENABLED
ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT = (
    _runtime_settings.ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT
)
ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS = _runtime_settings.ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS
TAPE_EXCEPTION_ENABLED = _runtime_settings.TAPE_EXCEPTION_ENABLED
OPEN_MOMENTUM_FAST_LANE_ENABLED = _runtime_settings.OPEN_MOMENTUM_FAST_LANE_ENABLED
MACRO_POSITION_COUNT_FLOOR = _runtime_settings.MACRO_POSITION_COUNT_FLOOR
ENFORCE_PREDICTION_BLOCKS = _runtime_settings.ENFORCE_PREDICTION_BLOCKS
ENFORCE_PREDICTION_WATCH_IN_CASH = _runtime_settings.ENFORCE_PREDICTION_WATCH_IN_CASH
STRATEGY_ENGINE_MODE = _runtime_settings.STRATEGY_ENGINE_MODE
RISK_POLICY_MODE = _runtime_settings.RISK_POLICY_MODE
ENFORCE_SESSION_MOMENTUM_GATE = _runtime_settings.ENFORCE_SESSION_MOMENTUM_GATE
ENFORCE_ADAPTIVE_CHURN_REENTRY = _runtime_settings.ENFORCE_ADAPTIVE_CHURN_REENTRY
SIGNAL_WORKER_COUNT = _runtime_settings.SIGNAL_WORKER_COUNT
RECENT_FAVORABLE_SETUP_TTL_MINUTES = _runtime_settings.RECENT_FAVORABLE_SETUP_TTL_MINUTES
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


def run_startup_tasks(app_container: ApplicationContainer | None = None) -> None:
    """Execute non-critical startup tasks. Call explicitly from an entrypoint
    or from tests by passing run_startup=True to `create_app()` when safe.
    """
    run_runtime_startup_tasks(
        sys.modules[__name__],
        app_container=app_container,
    )


def create_app(
    run_startup: bool = False,
    app_container: ApplicationContainer | None = None,
) -> Flask:
    """Application factory.

    Returns a new Flask app instance with the module's routes registered.
    When `run_startup` is True, execute non-critical startup tasks explicitly.
    """
    app_container = app_container or container
    return create_runtime_flask_app(
        import_name=__name__,
        runtime_module=sys.modules[__name__],
        app_container=app_container,
        run_startup=run_startup,
    )


def _ml_prediction_bucket(score) -> str:
    return entry_policy.ml_prediction_bucket(score)


def _buy_opportunity_sizing_enabled() -> bool:
    return os.getenv("BUY_OPPORTUNITY_SIZING_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


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
ALLOW_QUERY_STRING_SECRET = os.environ.get(
    "ALLOW_QUERY_STRING_SECRET",
    "false",
).strip().lower() in ("1", "true", "yes", "on")


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
        return cooldown_repo.recent_webhook_seen(key, symbol, action, price, WEBHOOK_DEDUPE_SECONDS)
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


_last_order: dict = {}  # {(symbol, action): datetime in ET} — reset on restart
_last_sell: dict = {}  # {symbol: (datetime in ET, price)} — last successful sell, for churn prevention
_trend_table: dict = {}  # {symbol: {direction, strength, consecutive_count, last_signal, last_time}}
_signal_history: dict = {}  # {symbol: [action, ...]} most recent first, max 10 — internal
_market_bias: dict = {}  # {symbol: {bias, reason, confidence}} — populated from market_context.json
_symbol_overrides: dict = {}

_symbol_override_service = SymbolOverrideService(
    path=Path(__file__).parent / "symbol_overrides.json",
    overrides=_symbol_overrides,
    log=logger,
)
_market_context_service = MarketContextService(
    path=Path(__file__).parent / "market_context.json",
    market_bias=_market_bias,
    expected_market_context_date=expected_market_context_date,
    log=logger,
)


def get_macro_risk(base_dir: Path | None = None):
    """Return macro policy from the same validated market context used for bias."""
    if (
        base_dir is None
        or Path(base_dir).resolve() == Path(__file__).parent.resolve()
        or not (Path(base_dir) / "market_context.json").exists()
    ):
        return _market_context_service.macro_risk()
    return _legacy_get_macro_risk(base_dir)


_trend_state_service = TrendStateService(
    approved_symbols=APPROVED_SYMBOLS,
    signal_history=_signal_history,
    trend_table=_trend_table,
    trades_repo=trades_repo,
    market_bias=_market_bias,
    symbol_market_alignment_map=SYMBOL_MARKET_ALIGNMENT,
    load_market_context=lambda: _market_context_service.load(),
    log=logger,
)
_momentum_service = MomentumService(
    market_data_service=market_data_service,
    iex_thin_symbols=IEX_THIN_SYMBOLS,
    log=logger,
)
get_momentum = _momentum_service.get_momentum
_setup_engine_service = build_default_setup_engine_service()
_regime_observation_service = build_default_regime_observation_service(
    base_dir=Path(__file__).resolve().parent,
    log=logger,
)


def _load_symbol_overrides():
    """Lazy-load symbol_overrides.json.

    Allows quick operator control without code changes:
      - disabled_symbols: block both BUY and SELL
      - buy_disabled: block BUY only
      - sell_only: block BUY only, allow SELL
    """
    _symbol_override_service.load()


def _symbol_override_block(symbol, action):
    """Return a reason string if a symbol override blocks this signal, else None."""
    return _symbol_override_service.block_reason(symbol, action)


def _compute_trend(recent_actions: list) -> dict:
    return _trend_state_service.compute_trend(recent_actions)


def _build_trend_table():
    """Build trend table for every approved symbol.

    Initializes all APPROVED_SYMBOLS as neutral/weak, then overlays recent
    signal history from trades.db where available. This ensures /status and
    trend-gate logic can see all approved symbols, not only symbols with DB history.
    """
    _trend_state_service.build_table()


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
        logger.info(
            f"Hydrated {loaded} active cooldowns from cooldowns table (of {len(rows)} total)"
        )
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
        logger.info(
            f"Hydrated {loaded} recent sells from recent_sells table (of {len(rows)} total)"
        )
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
    _trend_state_service.refresh_signal_history(symbol)


def _load_market_context():
    """Load same-day pre-market research into _market_bias.
    Lazy-refreshes when market_context.json mtime changes so the bot picks up
    each day's cron output without a service restart."""
    _market_context_service.load()


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
        build_tape_context=tape_service.build_tape_context,
        get_momentum=get_momentum,
        setup_context_deps=SetupContextDeps(
            build_snapshot=build_snapshot,
            evaluate_setup_policy=evaluate_setup_policy,
            upsert_recent_favorable_setup=context_repo.upsert_recent_favorable_setup,
            get_recent_favorable_setup=context_repo.get_recent_favorable_setup,
            now=datetime.now,
            recent_favorable_setup_ttl_minutes=RECENT_FAVORABLE_SETUP_TTL_MINUTES,
            log=logger,
            setup_engine=_setup_engine_service,
        ),
        log=logger,
        regime_observation_provider=_regime_observation_service.observe,
    )


def validate_secret(req):
    auth_header = req.headers.get("Authorization", "")
    bearer_secret = ""
    if auth_header.lower().startswith("bearer "):
        bearer_secret = auth_header.split(" ", 1)[1].strip()

    query_secret = req.args.get("secret", "")
    if query_secret and not ALLOW_QUERY_STRING_SECRET:
        logger.warning(
            f"Query-string secret rejected from {req.remote_addr}; "
            "use X-Webhook-Secret or Authorization header"
        )
        abort(401)

    secret = req.headers.get("X-Webhook-Secret") or bearer_secret
    if not secret and ALLOW_QUERY_STRING_SECRET:
        secret = query_secret

    if secret != WEBHOOK_SECRET:
        logger.warning(f"Invalid secret from {req.remote_addr}")
        abort(401)
    if query_secret and ALLOW_QUERY_STRING_SECRET:
        logger.warning(
            "Secret accepted from query parameter due to ALLOW_QUERY_STRING_SECRET; "
            "prefer X-Webhook-Secret or Authorization header"
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
        return _trend_state_service.symbol_market_alignment(symbol)

    except Exception as e:
        logger.error(f"_symbol_market_alignment failed for {symbol}: {e}")
        return {
            "cluster": "unknown",
            "benchmark": None,
            "aligned_for_buy": None,
            "reason": f"alignment error: {e}",
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


def _cluster_exposure(symbol, balance):
    """Return cluster exposure info for the symbol across current Alpaca positions."""
    if not balance:
        return []

    results = []
    try:
        positions = broker_service.list_positions()
        position_values = {p.symbol: float(p.market_value) for p in positions}

        for cluster_name, members in CORRELATION_CLUSTERS.items():
            if symbol not in members:
                continue

            cluster_value = sum(value for sym, value in position_values.items() if sym in members)

            exposure_pct = cluster_value / balance * 100
            limit_pct = CLUSTER_EXPOSURE_LIMITS.get(cluster_name, 100.0)

            results.append(
                {
                    "cluster": cluster_name,
                    "members": sorted(members),
                    "current_value": round(cluster_value, 2),
                    "exposure_pct": round(exposure_pct, 2),
                    "limit_pct": limit_pct,
                    "limit_hit": exposure_pct >= limit_pct,
                }
            )

    except Exception as e:
        logger.error(f"_cluster_exposure failed for {symbol}: {e}")

    return results


def _parse_signal_timestamp(data):
    """Best-effort parse of an optional TradingView/client timestamp.

    Supported keys:
      - timestamp
      - time
      - alert_time
      - alert_timestamp

    If no timestamp is present, return None so alerts continue to work.
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

    if session_5m is not None and session_5m <= _env_float(
        "SELL_CONTINUATION_MAX_5M_DROP_PCT", -0.20
    ):
        return None
    if session_15m is not None and session_15m <= _env_float(
        "SELL_CONTINUATION_MAX_15M_DROP_PCT", -0.10
    ):
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
        direction == "bearish" and strength == "confirmed" and consecutive_count >= 3
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


# Second-look safety thresholds.
# These are env-tunable so paper/live behavior can be adjusted without code edits.
MAX_SIGNAL_PRICE_DRIFT_PCT = float(os.environ.get("MAX_SIGNAL_PRICE_DRIFT_PCT", "0.35"))
MAX_BID_ASK_SPREAD_PCT = float(os.environ.get("MAX_BID_ASK_SPREAD_PCT", "0.10"))

_execution_adapter_service = ExecutionAdapterService(
    market_data_service=market_data_service,
    broker_service=broker_service,
    symbol_max_spread_pct=SYMBOL_MAX_SPREAD_PCT,
    max_bid_ask_spread_pct=MAX_BID_ASK_SPREAD_PCT,
    max_signal_price_drift_pct=MAX_SIGNAL_PRICE_DRIFT_PCT,
    one_bar_confirmation_enabled=ONE_BAR_CONFIRMATION_HOLD_ENABLED,
    one_bar_extension_threshold_pct=ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT,
    one_bar_timeout_seconds=ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS,
    log=logger,
)
_validate_spread_with_retry = _execution_adapter_service.validate_spread_with_retry
_pre_order_safety_check = _execution_adapter_service.pre_order_safety_check
_one_bar_confirmation_hold = _execution_adapter_service.one_bar_confirmation_hold

PORTFOLIO_ROTATION_ENABLED = os.environ.get(
    "PORTFOLIO_ROTATION_ENABLED", "false"
).lower().strip() in ("1", "true", "yes", "on")
PORTFOLIO_ROTATION_MIN_CANDIDATE_SCORE = int(
    os.environ.get("PORTFOLIO_ROTATION_MIN_CANDIDATE_SCORE", "12")
)
PORTFOLIO_ROTATION_MAX_PER_DAY = int(os.environ.get("PORTFOLIO_ROTATION_MAX_PER_DAY", "2"))
PORTFOLIO_ROTATION_MIN_HOLD_MINUTES = int(
    os.environ.get("PORTFOLIO_ROTATION_MIN_HOLD_MINUTES", "30")
)
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
        "excellent,high,good_on_pullbacks,good_if_holds_gap,good_if_breadth_holds",
    ).split(",")
    if s.strip()
}

_portfolio_rotation_service = PortfolioRotationService(
    broker_service=broker_service,
    trades_repo=trades_repo,
    trend_table=_trend_table,
    market_bias=_market_bias,
    open_entry_context=_open_entry_context,
    log_trade=(
        lambda signal, decision, order, account_state=None: (
            _trade_audit_recorder().record_execution(
                signal=signal,
                decision=decision,
                order=order,
                account_state=account_state,
            )
        )
    ),
    last_order=_last_order,
    write_cooldown=_write_cooldown,
    last_sell=_last_sell,
    write_recent_sell=_write_recent_sell,
    enabled=PORTFOLIO_ROTATION_ENABLED,
    max_per_day=PORTFOLIO_ROTATION_MAX_PER_DAY,
    min_candidate_score=PORTFOLIO_ROTATION_MIN_CANDIDATE_SCORE,
    min_hold_minutes=PORTFOLIO_ROTATION_MIN_HOLD_MINUTES,
    max_weak_plpc=PORTFOLIO_ROTATION_MAX_WEAK_PLPC,
    excluded_symbols=PORTFOLIO_ROTATION_EXCLUDED_SYMBOLS,
    allowed_risk_levels=PORTFOLIO_ROTATION_ALLOWED_RISK_LEVELS,
    allowed_entry_qualities=PORTFOLIO_ROTATION_ALLOWED_ENTRY_QUALITIES,
    log=logger,
)
_portfolio_rotation_count_today = _portfolio_rotation_service.count_today
_rotation_candidate_score = _portfolio_rotation_service.candidate_score
_weakest_rotation_holding = _portfolio_rotation_service.weakest_rotation_holding
_try_portfolio_rotation = _portfolio_rotation_service.try_rotation
_get_weakest_position_context = _portfolio_rotation_service.weakest_position_context


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
            f"recent_favorable_setup={bool(recent_favorable_setup)}",
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
        f"recent_favorable_setup={bool(recent_favorable_setup)}",
    )


def _evaluate_preflight(runtime_state: SignalRuntimeState):
    preflight = PreflightService(
        PreflightDeps(
            now_et=now_et,
            is_market_hours=is_market_hours,
            assert_position_exists=broker_service.assert_position_exists,
            get_position=broker_service.get_position,
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
    return preflight.evaluate(runtime_state)


def _update_trend_history(symbol: str, action: str) -> None:
    _trend_state_service.update_history(
        symbol,
        action,
        compute_trend_func=_compute_trend,
        refresh_signal_history=_refresh_signal_history,
    )


def _hydrate_pre_macro_context(
    *,
    symbol: str,
    action: str,
    account_state: dict,
    context_runtime,
) -> dict:
    return context_runtime.hydrate_pre_macro_context(
        get_macro_risk=get_macro_risk,
        base_dir=Path(__file__).parent,
        evaluate_buy_opportunity=evaluate_buy_opportunity,
        required_buy_confirmations=_required_buy_confirmations,
    )


def _apply_market_bias_context(
    *,
    action: str,
    account_state: dict,
    bias_entry: dict,
) -> None:
    context_builder_apply_market_bias_context(
        action=action,
        account_state=account_state,
        bias_entry=bias_entry,
    )


def _hydrate_session_context(*, context_runtime) -> None:
    context_runtime.hydrate_session_context(
        get_latest_session_momentum=get_latest_session_momentum,
        session_momentum_is_fresh=_session_momentum_is_fresh,
    )


def _hydrate_buy_momentum_context(
    *,
    symbol: str,
    action: str,
    account_state: dict,
    context_runtime,
) -> None:
    context_runtime.hydrate_buy_momentum_context()


def _hydrate_strategy_context(
    *,
    symbol: str,
    action: str,
    account_state: dict,
    context_runtime,
) -> None:
    context_runtime.hydrate_strategy_context(
        strategy_engine_mode=STRATEGY_ENGINE_MODE,
        evaluate_strategy_observe_only=evaluate_strategy_observe_only,
        symbol_market_alignment=_symbol_market_alignment,
        apply_size_cap=apply_size_cap,
        env_float=_env_float,
    )


def _allow_medium_confidence_momentum_override(
    symbol: str,
    action: str,
    decision: dict,
    account_state: dict,
    trend: dict,
    setup_obs: dict,
) -> tuple[bool, str]:
    """Allow medium Claude confidence only when deterministic evidence is exceptional."""
    try:
        if action != "buy":
            return False, "not_buy"

        if (decision or {}).get("confidence") != "medium":
            return False, "not_medium_confidence"

        trend = trend or {}
        account_state = account_state or {}
        setup_obs = setup_obs or {}

        trend_direction = trend.get("direction") or account_state.get("trend_direction")
        trend_strength = trend.get("strength") or account_state.get("trend_strength")
        momentum_direction = account_state.get("momentum_direction") or (
            account_state.get("momentum") or {}
        ).get("direction")
        session = account_state.get("session_momentum") or {}
        session_label = session.get("trend_label") or account_state.get("session_trend_label")

        prediction = account_state.get("prediction_gate") or {}
        prediction_decision = (
            prediction.get("prediction_decision")
            or prediction.get("decision")
            or account_state.get("prediction_decision")
        )
        prediction_score_raw = (
            prediction.get("prediction_score")
            or prediction.get("score")
            or account_state.get("prediction_score")
        )

        setup_action = (
            setup_obs.get("policy_action")
            or setup_obs.get("setup_policy_action")
            or account_state.get("setup_policy_action")
        )

        if setup_action in ("block", "error"):
            return False, f"setup_action={setup_action}"

        try:
            prediction_score = float(prediction_score_raw)
        except Exception:
            return False, "prediction_score_missing"

        checks = {
            "trend_direction": trend_direction == "bullish",
            "trend_strength": trend_strength == "confirmed",
            "momentum_direction": momentum_direction == "rising",
            "session_label": session_label == "strong_uptrend",
            "prediction_decision": prediction_decision == "pass",
            "prediction_score": prediction_score >= 8,
        }

        if not all(checks.values()):
            failed = ",".join(k for k, ok in checks.items() if not ok)
            return False, f"failed={failed}"

        reason = (
            "medium confidence allowed by deterministic momentum override: "
            f"trend={trend_direction}/{trend_strength}; "
            f"momentum={momentum_direction}; "
            f"session={session_label}; "
            f"prediction={prediction_decision}/{prediction_score:g}; "
            f"setup_action={setup_action}"
        )
        return True, reason

    except Exception as e:
        return False, f"override_error={e}"


def _build_signal_pipeline(app_container: ApplicationContainer | None = None):
    app_container = app_container or container
    return app_container.build_signal_pipeline(runtime=sys.modules[__name__])


def process_signal(data):
    return _build_signal_pipeline().run(data)


app = create_app(run_startup=False, app_container=container)


if __name__ == "__main__":
    create_app(run_startup=True).run(host="0.0.0.0", port=5000, debug=False)
