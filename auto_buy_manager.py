#!/usr/bin/env python3
"""
Internal auto-buy candidate manager.

This is the buy-side sibling to the position momentum auto-sell workflow:
- observe-only by default,
- uses Alpaca-derived session momentum and live feature snapshots,
- records candidate decisions for later comparison against TradingView alerts,
- only submits paper buys when both --live and AUTO_BUY_LIVE_BUYS=true are set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")
DB_PATH = BASE_DIR / "trades.db"


def _paper_runtime_default(paper_value: str, live_value: str) -> str:
    mode = os.getenv("EXECUTION_MODE", "paper").strip().lower()
    return paper_value if mode in {"paper", "dry_run"} else live_value


def reexec_under_venv_if_available() -> None:
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


def load_env_file(path: Path = ENV_FILE) -> bool:
    if not path.exists():
        return False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

    return True


load_env_file()

from bot_events import log_event
from market_time import ET, is_market_hours, now_et
from repositories import auto_buy_repo
from repositories.candidate_universe_repo import CandidateUniverseRepository
from repositories.prediction_repo import PredictionRepository
from risk.exposure import any_cluster_limit_hit, cluster_exposure
from services.candidate_universe_service import CandidateUniverseService
from services.ai_momentum_pattern_service import deterministic_momentum_pattern
from services.candidate_reference_service import candidate_reference_service
from services.learned_auto_buy_tiebreaker_service import (
    LearnedAutoBuyThresholds,
    LearnedAutoBuyTiebreakerService,
)
from services.intraday_trade_feedback_service import (
    IntradayTradeFeedbackService,
    build_default_intraday_trade_feedback_service,
)
from services.policies.entry_policy import ml_prediction_bucket
from runtime_config import is_cash_mode
from strategy_memory import memory_for_signal
from symbols_config import (
    APPROVED_SYMBOLS_LIST,
    CLUSTER_EXPOSURE_LIMITS,
    CORRELATION_CLUSTERS,
    INTERNAL_BAR_ONLY_SYMBOLS_LIST,
    SYMBOL_SIGNAL_SOURCE,
)


AUTO_BUY_LIVE_BUYS = os.getenv("AUTO_BUY_LIVE_BUYS", "false").lower() in ("1", "true", "yes", "on")
AUTO_BUY_ALLOW_TRADINGVIEW_LIVE = os.getenv(
    "AUTO_BUY_ALLOW_TRADINGVIEW_LIVE", "false"
).lower() in ("1", "true", "yes", "on")
AUTO_BUY_SIGNAL_MODE = os.getenv(
    "AUTO_BUY_SIGNAL_MODE", "legacy_source_gate"
).strip().lower()
TRADINGVIEW_ALERTS_DEPRECATED = os.getenv(
    "TRADINGVIEW_ALERTS_DEPRECATED", "false"
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_MIN_SCORE = float(os.getenv("AUTO_BUY_MIN_SCORE", "13"))
AUTO_BUY_WATCH_SCORE = float(os.getenv("AUTO_BUY_WATCH_SCORE", "7"))
AUTO_BUY_POSITION_SIZE_PCT = float(os.getenv("AUTO_BUY_POSITION_SIZE_PCT", "0.50"))
AUTO_BUY_STOP_LOSS_PCT = float(os.getenv("AUTO_BUY_STOP_LOSS_PCT", "1.00"))
AUTO_BUY_TAKE_PROFIT_PCT = float(os.getenv("AUTO_BUY_TAKE_PROFIT_PCT", "2.00"))
AUTO_BUY_MAX_ORDERS_PER_RUN = int(
    os.getenv("AUTO_BUY_MAX_ORDERS_PER_RUN", _paper_runtime_default("3", "1"))
)
AUTO_BUY_MAX_ACTIVE_POSITIONS = int(
    os.getenv("AUTO_BUY_MAX_ACTIVE_POSITIONS", _paper_runtime_default("8", "3"))
)
AUTO_BUY_MAX_DAILY_ORDERS = int(
    os.getenv("AUTO_BUY_MAX_DAILY_ORDERS", _paper_runtime_default("30", "12"))
)
AUTO_BUY_COOLDOWN_MINUTES = int(os.getenv("AUTO_BUY_COOLDOWN_MINUTES", "60"))
AUTO_BUY_SESSION_BUFFER_MINUTES = int(os.getenv("AUTO_BUY_SESSION_BUFFER_MINUTES", "10"))
APP_BUY_COOLDOWN_MINUTES = int(os.getenv("ORDER_COOLDOWN_MINUTES", "15"))
APP_RECENT_SELL_COOLDOWN_MINUTES = int(os.getenv("RECENT_SELL_COOLDOWN_MINUTES", "30"))
CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY = int(os.getenv("CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY", "1"))
AUTO_BUY_EXTENDED_VWAP_CAUTION_PCT = float(os.getenv("AUTO_BUY_EXTENDED_VWAP_CAUTION_PCT", "1.50"))
AUTO_BUY_UNCLASSIFIED_EXTENDED_BLOCK_PCT = float(
    os.getenv("AUTO_BUY_UNCLASSIFIED_EXTENDED_BLOCK_PCT", "1.50")
)
AUTO_BUY_ML_WEAK_BLOCK_ENABLED = os.getenv(
    "AUTO_BUY_ML_WEAK_BLOCK_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_ML_WEAK_BLOCK_SCORE = float(os.getenv("AUTO_BUY_ML_WEAK_BLOCK_SCORE", "45"))
AUTO_BUY_ML_WEAK_BLOCK_MIN_SAMPLE_SIZE = int(
    os.getenv("AUTO_BUY_ML_WEAK_BLOCK_MIN_SAMPLE_SIZE", "20")
)
AUTO_BUY_ML_WEAK_BUCKET_BLOCK_ENABLED = os.getenv(
    "AUTO_BUY_ML_WEAK_BUCKET_BLOCK_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED = os.getenv(
    "AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED",
    _paper_runtime_default("true", "false"),
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_EARLY_BUILD_ENABLED = os.getenv(
    "AUTO_BUY_EARLY_BUILD_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_EARLY_BUILD_MAX_SESSION_RETURN_PCT = float(
    os.getenv("AUTO_BUY_EARLY_BUILD_MAX_SESSION_RETURN_PCT", "0.90")
)
AUTO_BUY_EARLY_BUILD_MAX_VWAP_DIST_PCT = float(
    os.getenv("AUTO_BUY_EARLY_BUILD_MAX_VWAP_DIST_PCT", "0.70")
)
AUTO_BUY_EARLY_BUILD_MIN_SETUP_SCORE = float(
    os.getenv("AUTO_BUY_EARLY_BUILD_MIN_SETUP_SCORE", "50")
)
AUTO_BUY_MATURE_CHASE_ENABLED = os.getenv(
    "AUTO_BUY_MATURE_CHASE_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_MATURE_CHASE_SESSION_RETURN_PCT = float(
    os.getenv("AUTO_BUY_MATURE_CHASE_SESSION_RETURN_PCT", "1.50")
)
AUTO_BUY_MATURE_CHASE_VWAP_DIST_PCT = float(
    os.getenv("AUTO_BUY_MATURE_CHASE_VWAP_DIST_PCT", "1.00")
)
AUTO_BUY_EXTREME_CHASE_BLOCK_SESSION_RETURN_PCT = float(
    os.getenv("AUTO_BUY_EXTREME_CHASE_BLOCK_SESSION_RETURN_PCT", "2.50")
)
AUTO_BUY_EXTREME_CHASE_BLOCK_VWAP_DIST_PCT = float(
    os.getenv("AUTO_BUY_EXTREME_CHASE_BLOCK_VWAP_DIST_PCT", "1.25")
)
AUTO_BUY_LEARNED_TIEBREAKER_ENABLED = os.getenv(
    "AUTO_BUY_LEARNED_TIEBREAKER_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_LEARNED_TIEBREAKER_MIN_SAMPLE_SIZE = int(
    os.getenv(
        "AUTO_BUY_LEARNED_TIEBREAKER_MIN_SAMPLE_SIZE",
        _paper_runtime_default("10", "25"),
    )
)
AUTO_BUY_LEARNED_TIEBREAKER_MIN_WIN_RATE = float(
    os.getenv("AUTO_BUY_LEARNED_TIEBREAKER_MIN_WIN_RATE", "0.55")
)
AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_RETURN_PCT = float(
    os.getenv("AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_RETURN_PCT", "0.20")
)
AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_MFE_PCT = float(
    os.getenv("AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_MFE_PCT", "1.00")
)
AUTO_BUY_LEARNED_TIEBREAKER_MAX_AVG_MAE_PCT = float(
    os.getenv("AUTO_BUY_LEARNED_TIEBREAKER_MAX_AVG_MAE_PCT", "-1.50")
)
AUTO_BUY_LEARNED_TIEBREAKER_LOOKBACK_DAYS = int(
    os.getenv("AUTO_BUY_LEARNED_TIEBREAKER_LOOKBACK_DAYS", "10")
)
AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP = float(
    os.getenv(
        "AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP",
        _paper_runtime_default("6.0", "4.0"),
    )
)
AUTO_BUY_INTRADAY_FEEDBACK_ENABLED = os.getenv(
    "AUTO_BUY_INTRADAY_FEEDBACK_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
LEARNED_TIEBREAKER_SOFT_BLOCK_PREFIXES = (
    "bias_avoid",
    "setup_avoid",
    "negative_session",
    "15m_falling",
    "30m_falling",
    "ml_prediction_weak",
    "ml_prediction_weak_bucket",
)

_prediction_context_cache: dict[str, dict[str, Any]] = {}
_learned_tiebreaker_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_rolling_momentum_context_cache: dict[str, dict[str, Any]] | None = None
_intraday_feedback_service: IntradayTradeFeedbackService | None = None


def intraday_feedback_service() -> IntradayTradeFeedbackService:
    global _intraday_feedback_service
    if _intraday_feedback_service is None:
        _intraday_feedback_service = build_default_intraday_trade_feedback_service(DB_PATH)
    return _intraday_feedback_service


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _today() -> str:
    return now_et().strftime("%Y-%m-%d")


def internal_signal_execution_enabled() -> bool:
    """Whether internal bar candidates may execute for the full approved universe."""
    return TRADINGVIEW_ALERTS_DEPRECATED or AUTO_BUY_SIGNAL_MODE in {
        "internal_all",
        "bar_all",
        "all_internal",
    }


def tradingview_webhook_required_for_execution() -> bool:
    return not (AUTO_BUY_ALLOW_TRADINGVIEW_LIVE or internal_signal_execution_enabled())


def learned_tiebreaker_soft_block_only(block_reasons: list[str]) -> bool:
    if not block_reasons:
        return False
    for reason in block_reasons:
        if not str(reason).startswith(LEARNED_TIEBREAKER_SOFT_BLOCK_PREFIXES):
            return False
    return True


def _parse_et_timestamp(raw_ts: Any) -> datetime | None:
    if not raw_ts:
        return None
    try:
        ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
    except Exception:
        return None
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(ET).replace(tzinfo=None)


def auto_buy_prediction_context(symbol: str) -> dict[str, Any]:
    symbol = str(symbol or "").upper()
    if not symbol:
        return {"available": False, "ml_prediction_bucket": "unknown"}
    if symbol in _prediction_context_cache:
        return dict(_prediction_context_cache[symbol])

    result: dict[str, Any] = {
        "available": False,
        "ml_prediction_bucket": "unknown",
        "ml_prediction_score": None,
        "ml_prediction_confidence": None,
        "ml_prediction_sample_size": None,
        "ml_prediction_reason": None,
        "prediction_generated_at": None,
    }
    try:
        row = PredictionRepository(DB_PATH).serving_prediction_row(_today(), symbol)
    except Exception as exc:
        result["lookup_error"] = str(exc)
        _prediction_context_cache[symbol] = dict(result)
        return result

    if row:
        score = row.get("prediction_score")
        result.update(
            {
                "available": True,
                "prediction_score": score,
                "prediction_decision": "observe_only",
                "prediction_reason": row.get("reason"),
                "ml_prediction_score": score,
                "ml_prediction_bucket": ml_prediction_bucket(score),
                "ml_prediction_confidence": row.get("confidence"),
                "ml_prediction_sample_size": row.get("sample_size"),
                "ml_prediction_reason": row.get("reason"),
                "prediction_generated_at": row.get("prediction_generated_at"),
            }
        )

    _prediction_context_cache[symbol] = dict(result)
    return result


def load_rolling_momentum_context(
    path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Load rolling multi-day momentum context captured by rolling_momentum.py.

    This is read-only, cached per process, and deliberately does not fetch
    market data. If the provider file is missing or malformed, candidate
    scoring remains available with explicit missing context.
    """
    global _rolling_momentum_context_cache
    if path is None and _rolling_momentum_context_cache is not None:
        return {symbol: dict(value) for symbol, value in _rolling_momentum_context_cache.items()}

    source_path = path or (BASE_DIR / "rolling_momentum.json")
    try:
        loaded = json.loads(source_path.read_text())
    except Exception:
        result: dict[str, dict[str, Any]] = {}
    else:
        symbols = loaded.get("symbols") if isinstance(loaded, dict) else {}
        result = {
            str(symbol).upper(): dict(payload)
            for symbol, payload in symbols.items()
            if isinstance(payload, dict)
        } if isinstance(symbols, dict) else {}

    if path is None:
        _rolling_momentum_context_cache = {symbol: dict(value) for symbol, value in result.items()}
    return result


def rolling_momentum_for_symbol(symbol: str) -> dict[str, Any]:
    symbol = str(symbol or "").upper()
    return dict(load_rolling_momentum_context().get(symbol) or {})


def learned_auto_buy_tiebreaker_decision(candidate: dict[str, Any]) -> dict[str, Any]:
    target_date = _today()
    cache_key = (
        target_date,
        str(candidate.get("symbol") or "").upper(),
        str(candidate.get("symbol_pattern") or candidate.get("setup_label") or "unknown"),
    )
    if cache_key in _learned_tiebreaker_cache:
        return dict(_learned_tiebreaker_cache[cache_key])
    thresholds = LearnedAutoBuyThresholds(
        min_sample_size=AUTO_BUY_LEARNED_TIEBREAKER_MIN_SAMPLE_SIZE,
        min_win_rate=AUTO_BUY_LEARNED_TIEBREAKER_MIN_WIN_RATE,
        min_avg_return_pct=AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_RETURN_PCT,
        min_avg_mfe_pct=AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_MFE_PCT,
        max_avg_mae_pct=AUTO_BUY_LEARNED_TIEBREAKER_MAX_AVG_MAE_PCT,
        lookback_days=AUTO_BUY_LEARNED_TIEBREAKER_LOOKBACK_DAYS,
    )
    decision = LearnedAutoBuyTiebreakerService(
        CandidateUniverseRepository(DB_PATH),
        thresholds,
    ).decide(candidate, target_date=target_date)
    result = {
        "qualified": decision.qualified,
        "reason": decision.reason,
        "evidence": decision.evidence,
    }
    _learned_tiebreaker_cache[cache_key] = dict(result)
    return result


def session_elapsed_minutes(now=None) -> float:
    now = now or now_et()
    open_dt = now.replace(hour=9, minute=30, second=0, microsecond=0)
    return (now - open_dt).total_seconds() / 60.0


def should_collect_candidates(now=None) -> tuple[bool, str]:
    now = now or now_et()
    if not is_market_hours(now):
        return False, "market is closed"
    elapsed = session_elapsed_minutes(now)
    if elapsed < AUTO_BUY_SESSION_BUFFER_MINUTES:
        return False, (
            f"session elapsed {elapsed:.1f}m < "
            f"AUTO_BUY_SESSION_BUFFER_MINUTES={AUTO_BUY_SESSION_BUFFER_MINUTES}"
        )
    return True, f"session elapsed {elapsed:.1f}m"


def init_auto_buy_table() -> None:
    auto_buy_repo.init_tables(DB_PATH)


def latest_session(symbol: str) -> dict[str, Any]:
    return auto_buy_repo.latest_session(symbol, DB_PATH)


def latest_feature(symbol: str) -> dict[str, Any]:
    return auto_buy_repo.latest_feature(symbol, DB_PATH)


def load_market_context() -> dict[str, Any]:
    path = BASE_DIR / "market_context.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def held_symbols() -> set[str]:
    try:
        from services.broker_service import broker_service

        return {p.symbol.upper() for p in broker_service.list_positions()}
    except Exception:
        return set()


def client_order_id(symbol: str) -> str:
    ts = now_et().strftime("%Y%m%d%H%M%S")
    return f"autobuy-{symbol.lower()}-{ts}"


def auto_buy_orders_today() -> int:
    return auto_buy_repo.auto_buy_orders_today(_today(), DB_PATH)


def auto_buy_capacity_check() -> tuple[bool, str]:
    """Return whether auto-buy has room for another submitted order.

    Active exposure and gross daily attempts are intentionally separate. The
    position manager can exit early, so a small gross daily cap can leave the
    bot flat while still preventing fresh buys in a constructive market.
    """

    active_positions = held_symbols()
    active_count = len(active_positions)
    if active_count >= AUTO_BUY_MAX_ACTIVE_POSITIONS:
        return (
            False,
            "active auto-buy position cap reached: "
            f"{active_count} >= {AUTO_BUY_MAX_ACTIVE_POSITIONS}",
        )

    daily_orders = auto_buy_orders_today()
    if daily_orders >= AUTO_BUY_MAX_DAILY_ORDERS:
        return (
            False,
            "daily auto-buy gross order cap reached: "
            f"{daily_orders} >= {AUTO_BUY_MAX_DAILY_ORDERS}",
        )

    return (
        True,
        "auto-buy capacity ok: "
        f"active_positions={active_count}/{AUTO_BUY_MAX_ACTIVE_POSITIONS}, "
        f"daily_orders={daily_orders}/{AUTO_BUY_MAX_DAILY_ORDERS}",
    )


def recently_auto_bought(symbol: str, cooldown_minutes: int = AUTO_BUY_COOLDOWN_MINUTES) -> tuple[bool, str]:
    row = auto_buy_repo.latest_auto_buy_order(symbol, DB_PATH)
    if not row:
        return False, "no recent auto-buy order"

    try:
        ts = _parse_et_timestamp(row["timestamp"])
        if ts is None:
            raise ValueError("unparseable timestamp")
    except Exception:
        return True, "recent auto-buy timestamp could not be parsed"

    age_minutes = (now_et().replace(tzinfo=None) - ts).total_seconds() / 60.0
    if age_minutes < cooldown_minutes:
        return True, (
            f"last auto-buy order {age_minutes:.1f}m ago "
            f"< cooldown={cooldown_minutes}m order_id={row['order_id'] or '-'}"
        )

    return False, f"last auto-buy order {age_minutes:.1f}m ago"


def app_buy_cooldown_active(symbol: str, cooldown_minutes: int = APP_BUY_COOLDOWN_MINUTES) -> tuple[bool, str]:
    row = auto_buy_repo.app_buy_cooldown(symbol, DB_PATH)
    if not row:
        return False, "no app buy cooldown"

    ts = _parse_et_timestamp(row["last_order_time"])
    if ts is None:
        return True, "app buy cooldown timestamp could not be parsed"

    age_minutes = (now_et().replace(tzinfo=None) - ts).total_seconds() / 60.0
    if age_minutes < cooldown_minutes:
        return True, f"app buy cooldown active {age_minutes:.1f}m < {cooldown_minutes}m"
    return False, f"app buy cooldown expired {age_minutes:.1f}m ago"


def recent_sell_active(symbol: str, cooldown_minutes: int = APP_RECENT_SELL_COOLDOWN_MINUTES) -> tuple[bool, str]:
    row = auto_buy_repo.recent_sell(symbol, DB_PATH)
    if not row:
        return False, "no recent app sell"

    ts = _parse_et_timestamp(row["last_sell_time"])
    if ts is None:
        return True, "recent sell timestamp could not be parsed"

    age_minutes = (now_et().replace(tzinfo=None) - ts).total_seconds() / 60.0
    if age_minutes < cooldown_minutes:
        return True, (
            f"recent app sell active {age_minutes:.1f}m < {cooldown_minutes}m "
            f"price={row['last_sell_price']}"
        )
    return False, f"recent app sell expired {age_minutes:.1f}m ago"


def app_approved_buys_today(symbol: str) -> int:
    return auto_buy_repo.app_approved_buys_today(_today(), symbol, DB_PATH)


def broker_positions_and_balance() -> tuple[list[dict[str, Any]], float]:
    from services.broker_service import broker_service

    positions = []
    for p in broker_service.list_positions():
        positions.append({
            "symbol": p.symbol.upper(),
            "qty": getattr(p, "qty", None),
            "current_price": getattr(p, "current_price", None),
            "market_value": getattr(p, "market_value", None),
        })
    account = broker_service.get_account() or {}
    balance = _to_float(account.get("balance"), 0) or 0.0
    return positions, balance


def risk_cross_check(symbol: str) -> tuple[bool, str, dict[str, Any]]:
    if (
        is_cash_mode()
        and app_approved_buys_today(symbol) >= CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY
    ):
        return False, (
            f"app daily symbol buy limit reached: buys_today>="
            f"{CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY}"
        ), {}

    blocked, reason = app_buy_cooldown_active(symbol)
    if blocked:
        return False, reason, {}

    blocked, reason = recent_sell_active(symbol)
    if blocked:
        return False, reason, {}

    try:
        positions, balance = broker_positions_and_balance()
        cluster_checks = cluster_exposure(
            symbol,
            positions,
            balance,
            CORRELATION_CLUSTERS,
            CLUSTER_EXPOSURE_LIMITS,
        )
    except Exception as e:
        return False, f"risk cross-check failed while reading broker exposure: {e}", {}

    hit = any_cluster_limit_hit(cluster_checks)
    if hit:
        return False, (
            f"correlation cap: {hit['cluster']} exposure "
            f"{hit['exposure_pct']:.2f}% >= {hit['limit_pct']:.2f}%"
        ), {"correlation_exposure": cluster_checks}

    return True, "risk cross-check passed", {"correlation_exposure": cluster_checks}


def auto_buy_symbol_pattern(
    *,
    symbol: str,
    session: dict[str, Any],
    feature: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build observe-only symbol pattern metadata for candidate review.

    This intentionally has no scoring authority. It records the same pattern
    vocabulary used by canonical intelligence so auto-buy candidates can be
    compared against later lifecycle outcomes.
    """

    label = session.get("trend_label")
    session_score = _to_float(session.get("trend_score"), 0) or 0
    m5 = _to_float(session.get("momentum_5m_pct"), 0) or 0
    m15 = _to_float(session.get("momentum_15m_pct"), 0) or 0
    m30 = _to_float(session.get("momentum_30m_pct"), 0) or 0
    vwap = _to_float(session.get("distance_from_vwap_pct"), 0) or 0
    volume_ratio = _to_float(feature.get("volume_ratio_5m"), 0) or 0
    acceleration = _to_float(feature.get("momentum_acceleration_pct"))
    relative_strength = _to_float(feature.get("relative_strength_5m"), 0) or 0
    trend_direction = "neutral"
    trend_strength = "unknown"
    if label in {"strong_uptrend", "developing_uptrend"} or session_score >= 3:
        trend_direction = "bullish"
        trend_strength = "confirmed" if session_score >= 6 else "developing"
    elif label in {"downtrend", "fading"} or session_score <= -2:
        trend_direction = "bearish"
        trend_strength = "confirmed"

    if acceleration is not None:
        momentum_state = "accelerating" if acceleration >= 0.03 else "decelerating" if acceleration <= -0.03 else "mixed"
    elif m5 > 0 and m15 > 0 and m30 > 0:
        momentum_state = "accelerating"
    elif m15 < 0 or m30 < 0:
        momentum_state = "decelerating"
    else:
        momentum_state = "mixed"

    pattern = deterministic_momentum_pattern(
        symbol=symbol,
        action="buy",
        regime_state={
            "session_phase": "auto_buy_scan",
            "breakout_quality": context.get("entry_quality") or "unknown",
            "vwap_state": "above_vwap" if vwap >= 0 else "below_vwap",
            "participation_state": (
                "confirmed"
                if relative_strength >= 0.30
                else "not_confirmed"
            ),
            "volatility_stretch_state": "overextended" if vwap > 1.50 else "normal",
            "microstructure_liquidity_state": "unknown",
        },
        momentum_state={
            "state": momentum_state,
            "session_label": label,
            "volume_state": "surge" if volume_ratio >= 1.8 else "normal",
        },
        trend_state={
            "direction": trend_direction,
            "strength": trend_strength,
        },
        event_state={},
    )
    return {
        "symbol_pattern": pattern.get("pattern_label"),
        "pattern_directional_bias": pattern.get("directional_bias"),
        "pattern_confidence_quality": pattern.get("confidence_quality"),
        "pattern_runtime_effect": pattern.get("runtime_effect"),
        "pattern_source": "auto_buy_deterministic_pattern",
    }


def market_session_label() -> tuple[str | None, str]:
    """Return (trend_label, reason) for the overall market using QQQ then SPY as proxy.

    Used by the session momentum gate to suppress strong_buy_candidate decisions
    when the broad market is fading or in downtrend, regardless of individual scores.
    """
    for proxy in ("QQQ", "SPY"):
        row = latest_session(proxy)
        label = row.get("trend_label")
        if label:
            return label, f"market_proxy={proxy}"
    return None, "no_market_proxy_available"


SUPPRESSED_LABELS = {"fading", "downtrend"}


def strong_buy_signals_today(symbol: str) -> int:
    """Count strong_buy_candidate signals that were actually submitted today."""
    return auto_buy_repo.strong_buy_signals_today(symbol, _today(), DB_PATH)


def write_app_buy_cooldown(symbol: str) -> None:
    auto_buy_repo.write_app_buy_cooldown(symbol, now_et().isoformat(), DB_PATH)


def evaluate_auto_buy_candidate(
    *,
    symbol: str,
    session: dict[str, Any],
    feature: dict[str, Any],
    context: dict[str, Any],
    rolling_context: dict[str, Any] | None = None,
    intraday_feedback_evidence: dict[str, dict[str, Any]] | None = None,
    held: set[str] | None = None,
    signal_source: str = "internal_bar_only",
) -> dict[str, Any]:
    held = held or set()
    symbol = symbol.upper()

    if symbol in held:
        return {
            "symbol": symbol,
            "decision": "skip",
            "score": 0,
            "severity": "held",
            "reason": "symbol already held",
            "symbol_pattern": "held_symbol_not_evaluated",
            "pattern_directional_bias": "not_applicable",
            "pattern_confidence_quality": "not_applicable",
            "pattern_runtime_effect": "observe_only_no_live_authority",
            "pattern_source": "auto_buy_held_short_circuit",
        }

    score = 0.0
    reasons = []

    bias = context.get("bias")
    entry_quality = context.get("entry_quality")
    risk_level = context.get("risk_level")
    avoid_type = context.get("avoid_type")
    rolling_context = rolling_context or {}

    if bias == "avoid":
        score -= 5
        reasons.append(f"bias_avoid:{avoid_type or 'unspecified'}:-5")
    elif bias == "buy":
        score += 2
        reasons.append("market_bias_buy:+2")

    if entry_quality in ("good_if_holds_gap", "good_on_pullbacks", "excellent"):
        score += 2
        reasons.append(f"entry_quality_{entry_quality}:+2")
    elif entry_quality in ("avoid_chasing", "do_not_chase", "poor"):
        score -= 4
        reasons.append(f"entry_quality_{entry_quality}:-4")

    if risk_level == "high":
        score -= 2
        reasons.append("risk_high:-2")
    elif risk_level == "low":
        score += 1
        reasons.append("risk_low:+1")

    label = session.get("trend_label")
    session_score = _to_float(session.get("trend_score"), 0) or 0
    m5 = _to_float(session.get("momentum_5m_pct"), 0) or 0
    m15 = _to_float(session.get("momentum_15m_pct"), 0) or 0
    m30 = _to_float(session.get("momentum_30m_pct"), 0) or 0
    vwap = _to_float(session.get("distance_from_vwap_pct"), 0) or 0
    session_return = _to_float(session.get("session_return_pct"), 0) or 0
    five_day_return = _to_float(rolling_context.get("five_day_return_pct"))
    prior_day_return = _to_float(rolling_context.get("prior_day_return_pct"))
    current_vs_prior_close = _to_float(
        rolling_context.get("current_price_vs_prior_close_pct")
    )
    extension_from_recent_base = _to_float(
        rolling_context.get("extension_from_recent_base_pct")
    )
    rolling_continuation_score = _to_float(
        rolling_context.get("continuation_score")
    )
    rolling_trend_context = rolling_context.get("trend_context")

    if five_day_return is not None:
        if five_day_return >= 2.0 and label in {"strong_uptrend", "developing_uptrend"}:
            score += 2
            reasons.append(f"5d_trend_aligned:+2({five_day_return:.2f}%)")
        elif five_day_return >= 1.0 and session_return >= 0.25:
            score += 1
            reasons.append(f"5d_constructive:+1({five_day_return:.2f}%)")
        elif five_day_return <= -2.0 and label in {"downtrend", "fading"}:
            score -= 2
            reasons.append(f"5d_negative_aligned:-2({five_day_return:.2f}%)")
        elif five_day_return <= -1.0 and session_return <= -0.25:
            score -= 1
            reasons.append(f"5d_weak_context:-1({five_day_return:.2f}%)")

    if rolling_continuation_score is not None:
        if rolling_continuation_score >= 4:
            score += 1
            reasons.append(f"rolling_continuation_score:+1({rolling_continuation_score:.0f})")
        elif rolling_continuation_score <= -4:
            score -= 1
            reasons.append(f"rolling_continuation_score:-1({rolling_continuation_score:.0f})")

    if label == "strong_uptrend" or session_score >= 6:
        score += 4
        reasons.append("strong_session:+4")
    elif label == "developing_uptrend" or session_score >= 3:
        score += 3
        reasons.append("developing_session:+3")
    elif label in ("downtrend", "fading") or session_score <= -2:
        score -= 4
        reasons.append(f"negative_session_{label}:-4")

    if m15 > 0.20:
        score += 2
        reasons.append("15m_rising:+2")
    elif m15 < -0.20:
        score -= 3
        reasons.append("15m_falling:-3")

    if m30 > 0.35:
        score += 2
        reasons.append("30m_rising:+2")
    elif m30 < -0.35:
        score -= 3
        reasons.append("30m_falling:-3")

    if m5 > 0.10:
        score += 1
        reasons.append("5m_rising:+1")
    elif m5 < -0.25:
        score -= 1
        reasons.append("5m_sharp_drop:-1")

    if 0.05 <= vwap <= 1.00:
        score += 1
        reasons.append("constructive_vwap:+1")
    elif vwap > AUTO_BUY_EXTENDED_VWAP_CAUTION_PCT:
        score -= 5
        reasons.append(f"extended_vwap>{AUTO_BUY_EXTENDED_VWAP_CAUTION_PCT:.2f}:-5")
    elif vwap < -0.25:
        score -= 1
        reasons.append("below_vwap:-1")

    if session_return > 0.50:
        score += 1
        reasons.append("positive_session_return:+1")

    setup_rec = feature.get("setup_recommendation")
    setup_label = feature.get("setup_label")
    setup_score = _to_float(feature.get("setup_score"), 0) or 0

    if setup_rec == "favorable":
        score += 3
        reasons.append("setup_favorable:+3")
    elif setup_rec == "watch":
        score += 1
        reasons.append("setup_watch:+1")
    elif setup_rec == "avoid":
        score -= 4
        reasons.append("setup_avoid:-4")

    if setup_label == "unclassified_transition":
        score -= 3
        reasons.append("setup_unclassified_transition:-3")

    if setup_score >= 70:
        score += 2
        reasons.append("setup_score>=70:+2")
    elif setup_score <= 20:
        score -= 2
        reasons.append("setup_score<=20:-2")

    early_constructive_build = (
        AUTO_BUY_EARLY_BUILD_ENABLED
        and setup_score >= AUTO_BUY_EARLY_BUILD_MIN_SETUP_SCORE
        and setup_rec in {"favorable", "watch"}
        and label in {"developing_uptrend", "strong_uptrend"}
        and 0.0 <= session_return <= AUTO_BUY_EARLY_BUILD_MAX_SESSION_RETURN_PCT
        and -0.10 <= vwap <= AUTO_BUY_EARLY_BUILD_MAX_VWAP_DIST_PCT
        and m5 >= 0.05
        and m15 >= 0.10
        and m30 >= 0.0
    )
    if early_constructive_build:
        score += 3
        reasons.append(
            "early_constructive_build:+3"
            f"(session={session_return:.2f}%,vwap={vwap:.2f}%,setup={setup_score:.1f})"
        )

    mature_chase = (
        AUTO_BUY_MATURE_CHASE_ENABLED
        and session_return >= AUTO_BUY_MATURE_CHASE_SESSION_RETURN_PCT
        and vwap >= AUTO_BUY_MATURE_CHASE_VWAP_DIST_PCT
        and setup_label not in {
            "confirmed_near_vwap_recovery",
            "near_vwap_weak_strength_followthrough",
        }
    )
    extreme_chase = (
        mature_chase
        and session_return >= AUTO_BUY_EXTREME_CHASE_BLOCK_SESSION_RETURN_PCT
        and vwap >= AUTO_BUY_EXTREME_CHASE_BLOCK_VWAP_DIST_PCT
    )
    if mature_chase:
        score -= 4
        reasons.append(
            "mature_chase_extension:-4"
            f"(session={session_return:.2f}%,vwap={vwap:.2f}%)"
        )

    strategy_memory = memory_for_signal(
        symbol,
        {
            "setup_quality": {
                "label": setup_label,
                "recommendation": setup_rec,
            },
            "setup_observation": {
                "setup_label": setup_label,
                "setup_score": setup_score,
            },
            "prediction_observation": {
                "decision": "unknown",
            },
            "buy_opportunity": {
                "recommendation": "unknown",
            },
            "session_observation": {
                "label": label,
            },
        },
    )
    learned_min_setup_score = strategy_memory.get("min_setup_score")
    memory_rec = str(strategy_memory.get("recommendation") or "none").strip().lower()
    strategy_memory_caution_gate = False
    if strategy_memory.get("available"):
        reasons.append(
            "strategy_memory:"
            f"{memory_rec}:min_setup={learned_min_setup_score}:"
            f"trades={((strategy_memory.get('symbol_memory') or {}).get('trades'))}"
        )
        if isinstance(learned_min_setup_score, int) and setup_score < learned_min_setup_score:
            if memory_rec == "avoid":
                reasons.append(
                    f"strategy_memory_avoid_setup_below_min:{setup_score:.1f}<"
                    f"{learned_min_setup_score}"
                )
            elif memory_rec == "caution":
                strategy_memory_caution_gate = True
                score -= 4
                reasons.append(
                    f"strategy_memory_caution_setup_below_min:{setup_score:.1f}<"
                    f"{learned_min_setup_score}:-4"
                )
    else:
        reasons.append(f"strategy_memory:unavailable:{strategy_memory.get('reason')}")

    relative_strength = _to_float(feature.get("relative_strength_5m"), 0) or 0
    ret5 = _to_float(feature.get("ret_5m"), 0) or 0
    ret15 = _to_float(feature.get("ret_15m"), 0) or 0
    feature_vwap = _to_float(feature.get("distance_from_vwap"), 0) or 0

    if relative_strength >= 0.30:
        score += 1
        reasons.append("relative_strength:+1")
    if ret5 > 0 and ret15 > 0:
        score += 1
        reasons.append("feature_5m_15m_positive:+1")
    if feature_vwap > 1.50:
        score -= 2
        reasons.append("feature_vwap_extended:-2")

    # Momentum acceleration modifier — same thresholds as setup_engine._score_modifiers.
    # feature_snapshots already computes this field every bar cycle.
    mom_acc = _to_float(feature.get("momentum_acceleration_pct"))
    if mom_acc is not None:
        if mom_acc <= -0.05:
            score -= 12
            reasons.append(f"mom_strong_decel({mom_acc:.3f}):-12")
        elif mom_acc <= -0.03:
            score -= 8
            reasons.append(f"mom_decel({mom_acc:.3f}):-8")
        elif mom_acc >= 0.05:
            score += 6
            reasons.append(f"mom_strong_accel({mom_acc:.3f}):+6")
        elif mom_acc >= 0.03:
            score += 3
            reasons.append(f"mom_accel({mom_acc:.3f}):+3")

    hard_block_reasons = []

    volume_ratio = _to_float(feature.get("volume_ratio_5m"), 0) or 0
    prediction_context = auto_buy_prediction_context(symbol)
    ml_score = _to_float(prediction_context.get("ml_prediction_score"))
    ml_sample = int(_to_float(prediction_context.get("ml_prediction_sample_size"), 0) or 0)
    ml_bucket = str(prediction_context.get("ml_prediction_bucket") or "").strip().lower()
    if prediction_context.get("lookup_error"):
        reasons.append(f"ml_prediction_lookup_error:{prediction_context['lookup_error']}")
    elif prediction_context.get("available"):
        reasons.append(
            "ml_prediction:"
            f"{prediction_context.get('ml_prediction_bucket')}"
            f":score={ml_score}"
            f":sample={ml_sample}"
        )
    else:
        reasons.append("ml_prediction:unavailable")

    # A symbol can occasionally buck its own fading/downtrend session label via two paths:
    # 1. Full-session: strong session return + relative strength confirm sustained divergence.
    # 2. Acceleration: real-time momentum surge with volume confirms an intraday impulse
    #    early in the move (lower session_return bar, but acceleration + volume required).
    _bucking_full_session = (
        session_return >= AUTO_BUY_BUCKING_TAPE_MIN_SESSION_RETURN_PCT
        and relative_strength >= AUTO_BUY_BUCKING_TAPE_MIN_RELATIVE_STRENGTH
    )
    _bucking_acceleration = (
        mom_acc is not None
        and mom_acc >= AUTO_BUY_BUCKING_TAPE_MIN_ACCEL_PCT
        and volume_ratio >= AUTO_BUY_BUCKING_TAPE_MIN_VOLUME_RATIO
        and session_return >= AUTO_BUY_BUCKING_TAPE_MIN_EARLY_SESSION_RETURN_PCT
    )
    bucking_negative_tape = label in ("downtrend", "fading") and (
        _bucking_full_session or _bucking_acceleration
    )
    if bucking_negative_tape:
        if _bucking_acceleration and not _bucking_full_session:
            reasons.append(
                f"bucking_{label}_tape(accel):"
                f"mom_acc={mom_acc:.3f} "
                f"volume_ratio={volume_ratio:.2f} "
                f"session_return={session_return:.3f}%"
            )
        else:
            reasons.append(
                f"bucking_{label}_tape:"
                f"session_return={session_return:.3f}% "
                f"relative_strength={relative_strength:.3f}"
            )

    if bias == "avoid":
        hard_block_reasons.append(f"bias_avoid:{avoid_type or 'unspecified'}")
    if setup_rec == "avoid":
        hard_block_reasons.append("setup_avoid")
    if setup_label == "unclassified_transition" and vwap > AUTO_BUY_UNCLASSIFIED_EXTENDED_BLOCK_PCT:
        hard_block_reasons.append(
            f"unclassified_extended_vwap:{vwap:.3f}>{AUTO_BUY_UNCLASSIFIED_EXTENDED_BLOCK_PCT:.2f}"
        )
    if extreme_chase:
        hard_block_reasons.append(
            "extreme_mature_chase:"
            f"session_return={session_return:.3f}>={AUTO_BUY_EXTREME_CHASE_BLOCK_SESSION_RETURN_PCT:.2f};"
            f"vwap={vwap:.3f}>={AUTO_BUY_EXTREME_CHASE_BLOCK_VWAP_DIST_PCT:.2f}"
        )
    if (
        strategy_memory.get("available")
        and memory_rec == "avoid"
        and isinstance(learned_min_setup_score, int)
        and setup_score < learned_min_setup_score
    ):
        hard_block_reasons.append(
            "strategy_memory_avoid:"
            f"setup_score={setup_score:.1f}<learned_min={learned_min_setup_score};"
            f"{strategy_memory.get('reason')}"
        )
    if label in ("downtrend", "fading"):
        if not bucking_negative_tape:
            hard_block_reasons.append(f"negative_session:{label}")
    if m15 < -0.20:
        if not bucking_negative_tape:
            hard_block_reasons.append(f"15m_falling:{m15:.3f}")
        else:
            reasons.append(f"15m_falling_soft:{m15:.3f}")
    if m30 < -0.35:
        if not bucking_negative_tape:
            hard_block_reasons.append(f"30m_falling:{m30:.3f}")
        else:
            reasons.append(f"30m_falling_soft:{m30:.3f}")
    if (
        AUTO_BUY_ML_WEAK_BLOCK_ENABLED
        and ml_score is not None
        and ml_score < AUTO_BUY_ML_WEAK_BLOCK_SCORE
        and ml_sample >= AUTO_BUY_ML_WEAK_BLOCK_MIN_SAMPLE_SIZE
    ):
        hard_block_reasons.append(
            "ml_prediction_weak:"
            f"{ml_score:.2f}<"
            f"{AUTO_BUY_ML_WEAK_BLOCK_SCORE:.2f};"
            f"sample={ml_sample}"
        )
    elif AUTO_BUY_ML_WEAK_BUCKET_BLOCK_ENABLED and ml_bucket == "weak_below_45":
        hard_block_reasons.append(
            "ml_prediction_weak_bucket:"
            f"{prediction_context.get('ml_prediction_bucket')};"
            f"score={ml_score};sample={ml_sample}"
        )

    pattern = auto_buy_symbol_pattern(
        symbol=symbol,
        session=session,
        feature=feature,
        context=context,
    )
    intraday_feedback = {
        "status": "disabled",
        "runtime_effect": "disabled_no_intraday_feedback",
        "score_penalty": 0.0,
        "hard_block_reason": None,
        "evidence": {},
    }
    if AUTO_BUY_INTRADAY_FEEDBACK_ENABLED:
        intraday_feedback = intraday_feedback_service().assess_candidate(
            target_date=_today(),
            candidate={
                "symbol": symbol,
                "setup_recommendation": setup_rec,
                "setup_policy_action": setup_rec,
                "setup_label": setup_label,
                "ml_prediction_bucket": prediction_context.get("ml_prediction_bucket"),
                "session_trend_label": label,
                **pattern,
            },
            evidence=intraday_feedback_evidence,
            allow_authority=not is_cash_mode(),
        )
        feedback_status = str(intraday_feedback.get("status") or "neutral")
        feedback_penalty = _to_float(intraday_feedback.get("score_penalty"), 0) or 0
        if feedback_penalty:
            score += feedback_penalty
            reasons.append(
                "intraday_feedback_penalty:"
                f"{feedback_status}:{feedback_penalty:+.1f}:"
                f"{intraday_feedback.get('feedback_key')}"
            )
        if feedback_status == "block" and intraday_feedback.get("hard_block_reason"):
            hard_block_reasons.append(str(intraday_feedback["hard_block_reason"]))
        elif feedback_status.startswith("would_"):
            reasons.append(
                "intraday_feedback_observed_no_authority:"
                f"{feedback_status}:{intraday_feedback.get('feedback_key')}"
            )

    hard_block_reason = "; ".join(hard_block_reasons) if hard_block_reasons else None

    strong_threshold = AUTO_BUY_MIN_SCORE
    execution_signal_mode = (
        "internal_all" if internal_signal_execution_enabled() else "legacy_source_gate"
    )
    requires_webhook = signal_source == "tradingview_alert" and tradingview_webhook_required_for_execution()
    if requires_webhook:
        strong_threshold = AUTO_BUY_MIN_SCORE + 4.0
        reasons.append(f"webhook_symbol_candidate_threshold:{strong_threshold:.1f}")
    elif signal_source == "tradingview_alert":
        reasons.append(f"internal_signal_execution:{execution_signal_mode}")

    if hard_block_reasons:
        decision = "skip"
        severity = "blocked"
    elif strategy_memory_caution_gate and score >= AUTO_BUY_WATCH_SCORE:
        decision = "watch"
        severity = "medium"
        reasons.append("strategy_memory_caution_caps_at_watch")
    elif (
        score >= strong_threshold
        and (setup_rec != "watch" or AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED)
    ):
        decision = "strong_buy_candidate"
        severity = "high"
    elif score >= AUTO_BUY_WATCH_SCORE:
        decision = "watch"
        severity = "medium"
    else:
        decision = "skip"
        severity = "low"

    learned_tiebreaker_applied = False
    learned_tiebreaker_reason = None
    learned_tiebreaker_evidence: dict[str, Any] = {}
    learned_tiebreaker_overrode_soft_blocks = False
    learned_tiebreaker_original_hard_block_reason = hard_block_reason
    learned_tiebreaker_soft_blocks_only = learned_tiebreaker_soft_block_only(hard_block_reasons)
    threshold_gap = round(float(strong_threshold) - float(score), 4)
    learned_tiebreaker_allowed = (
        AUTO_BUY_LEARNED_TIEBREAKER_ENABLED
        and not is_cash_mode()
        and not requires_webhook
        and (not hard_block_reasons or learned_tiebreaker_soft_blocks_only)
        and decision in {"watch", "skip"}
        and score >= AUTO_BUY_WATCH_SCORE
        and threshold_gap <= AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP
    )
    if learned_tiebreaker_allowed:
        tiebreaker = learned_auto_buy_tiebreaker_decision(
            {
                "symbol": symbol,
                "score": score,
                "threshold": strong_threshold,
                "setup_label": setup_label,
                "session_trend_label": label,
                **pattern,
            }
        )
        learned_tiebreaker_reason = tiebreaker.get("reason")
        evidence = tiebreaker.get("evidence")
        learned_tiebreaker_evidence = evidence if isinstance(evidence, dict) else {}
        if tiebreaker.get("qualified"):
            decision = "strong_buy_candidate"
            severity = "high"
            learned_tiebreaker_applied = True
            if hard_block_reasons:
                learned_tiebreaker_overrode_soft_blocks = True
                hard_block_reason = None
            reasons.append(
                "learned_tiebreaker_promoted:"
                f"{learned_tiebreaker_reason}:"
                f"gap={threshold_gap:.2f}"
            )
        else:
            reasons.append(f"learned_tiebreaker_observed:{learned_tiebreaker_reason}")
    return {
        "symbol": symbol,
        "signal_source": signal_source,
        "execution_signal_mode": execution_signal_mode,
        "requires_tradingview_webhook": requires_webhook,
        "decision": decision,
        "severity": severity,
        "score": round(score, 2),
        "strong_buy_threshold": strong_threshold,
        "reason": "; ".join(reasons) if reasons else "no positive auto-buy evidence",
        "hard_block_reason": hard_block_reason,
        "market_bias": bias,
        "entry_quality": entry_quality,
        "risk_level": risk_level,
        "session_trend_label": label,
        "session_trend_score": session_score,
        "session_return_pct": session_return,
        "five_day_return_pct": five_day_return,
        "prior_day_return_pct": prior_day_return,
        "current_price_vs_prior_close_pct": current_vs_prior_close,
        "extension_from_recent_base_pct": extension_from_recent_base,
        "rolling_continuation_score": rolling_continuation_score,
        "rolling_trend_context": rolling_trend_context,
        "rolling_momentum_generated_at": rolling_context.get("generated_at"),
        "rolling_momentum_latest_bar_time_et": rolling_context.get("latest_bar_time_et"),
        "rolling_momentum_data_feed": rolling_context.get("data_feed"),
        "rolling_momentum_market_days_found": rolling_context.get("market_days_found"),
        "rolling_momentum_last_5_market_days": rolling_context.get("last_5_market_days") or [],
        "rolling_momentum_source": (
            "rolling_momentum_json"
            if rolling_context
            else "missing"
        ),
        "momentum_5m_pct": m5,
        "momentum_15m_pct": m15,
        "momentum_30m_pct": m30,
        "distance_from_vwap_pct": vwap,
        "setup_label": setup_label,
        "setup_recommendation": setup_rec,
        "setup_score": setup_score,
        "strategy_memory_recommendation": memory_rec,
        "strategy_memory_min_setup_score": learned_min_setup_score,
        "strategy_memory_reason": strategy_memory.get("reason"),
        "strategy_memory_available": bool(strategy_memory.get("available")),
        "learned_tiebreaker_enabled": bool(AUTO_BUY_LEARNED_TIEBREAKER_ENABLED),
        "learned_tiebreaker_allowed": bool(learned_tiebreaker_allowed),
        "learned_tiebreaker_applied": bool(learned_tiebreaker_applied),
        "learned_tiebreaker_reason": learned_tiebreaker_reason,
        "learned_tiebreaker_evidence": learned_tiebreaker_evidence,
        "learned_tiebreaker_soft_blocks_only": bool(learned_tiebreaker_soft_blocks_only),
        "learned_tiebreaker_overrode_soft_blocks": bool(learned_tiebreaker_overrode_soft_blocks),
        "learned_tiebreaker_original_hard_block_reason": learned_tiebreaker_original_hard_block_reason,
        "learned_tiebreaker_runtime_effect": (
            "paper_only_tiebreaker_authority"
            if learned_tiebreaker_applied
            else "observe_only_no_live_authority"
        ),
        "intraday_feedback_enabled": bool(AUTO_BUY_INTRADAY_FEEDBACK_ENABLED),
        "intraday_feedback_status": intraday_feedback.get("status"),
        "intraday_feedback_key": intraday_feedback.get("feedback_key"),
        "intraday_feedback_score_penalty": intraday_feedback.get("score_penalty"),
        "intraday_feedback_hard_block_reason": intraday_feedback.get("hard_block_reason"),
        "intraday_feedback_evidence": intraday_feedback.get("evidence") or {},
        "intraday_feedback_runtime_effect": intraday_feedback.get("runtime_effect"),
        "early_constructive_build": bool(early_constructive_build),
        "mature_chase": bool(mature_chase),
        "extreme_chase": bool(extreme_chase),
        "feature_snapshot_id": feature.get("id"),
        **prediction_context,
        **pattern,
    }


def enrich_candidate_with_reference_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(candidate)
    if enriched.get("reference_price") is not None:
        return enriched
    enriched.update(
        candidate_reference_service.candidate_reference_snapshot(str(enriched.get("symbol") or ""))
    )
    return enriched


def log_candidate(candidate: dict[str, Any], live_buy_enabled: bool, order: dict[str, Any] | None = None) -> None:
    order = order or {}
    timestamp = now_et().isoformat()
    candidate = enrich_candidate_with_reference_snapshot(candidate)
    auto_buy_repo.init_tables(DB_PATH)
    auto_buy_repo.insert_candidate_and_snapshot(
        timestamp=timestamp,
        created_at=now_et().isoformat(),
        candidate=candidate,
        live_buy_enabled=live_buy_enabled,
        order=order,
        candidate_json=json.dumps(candidate, sort_keys=True, default=str),
        order_json=json.dumps(order, sort_keys=True, default=str),
        db_path=DB_PATH,
    )
    feedback_status = str(candidate.get("intraday_feedback_status") or "neutral")
    if feedback_status not in {"neutral", "disabled"}:
        try:
            auto_buy_repo.insert_intraday_feedback_event(
                created_at=now_et().isoformat(),
                target_date=_today(),
                symbol=candidate.get("symbol"),
                feedback_key=str(candidate.get("intraday_feedback_key") or "unknown"),
                status=feedback_status,
                score_penalty=_to_float(candidate.get("intraday_feedback_score_penalty")),
                hard_block_reason=candidate.get("intraday_feedback_hard_block_reason"),
                evidence_json=json.dumps(
                    candidate.get("intraday_feedback_evidence") or {},
                    sort_keys=True,
                    default=str,
                ),
                candidate_json=json.dumps(candidate, sort_keys=True, default=str),
                runtime_effect=str(
                    candidate.get("intraday_feedback_runtime_effect")
                    or "observe_only_no_intraday_feedback"
                ),
                db_path=DB_PATH,
            )
        except Exception as exc:
            print(
                f"[WARN] intraday feedback capture failed for {candidate.get('symbol')}: {exc}",
                file=sys.stderr,
            )
    try:
        CandidateUniverseService(CandidateUniverseRepository(DB_PATH)).persist_scored_candidate(
            candidate_ts=timestamp,
            symbol=candidate["symbol"],
            action="buy",
            score=candidate.get("score"),
            threshold=AUTO_BUY_MIN_SCORE,
            taken=bool(order.get("order_id")),
            source="auto_buy_manager",
            decision=candidate.get("decision"),
            reason=candidate.get("reason") or candidate.get("hard_block_reason"),
            setup_label=candidate.get("setup_label"),
            regime=candidate.get("market_bias"),
            session_phase=candidate.get("session_trend_label"),
            payload={
                "candidate": candidate,
                "order_submitted": bool(order.get("order_id")),
                "live_buy_enabled": live_buy_enabled,
            },
        )
    except Exception as exc:
        print(f"[WARN] candidate universe capture failed for {candidate.get('symbol')}: {exc}", file=sys.stderr)


def log_auto_buy_order(candidate: dict[str, Any], order: dict[str, Any]) -> bool:
    """Persist submitted auto-buy orders to the canonical trades ledger."""
    order_id = order.get("order_id") if isinstance(order, dict) else None
    if not order_id:
        return False

    try:
        qty = int(float(order.get("qty") or 0))
    except (TypeError, ValueError):
        qty = None

    if auto_buy_repo.trade_order_exists(order_id, DB_PATH):
        return False

    enrich_auto_buy_trade_context(candidate)

    auto_buy_repo.insert_auto_buy_trade(
        timestamp=now_et().strftime("%Y-%m-%d %H:%M:%S"),
        candidate=candidate,
        order=order,
        qty=qty,
        position_size_pct=AUTO_BUY_POSITION_SIZE_PCT,
        stop_loss_pct=AUTO_BUY_STOP_LOSS_PCT,
        take_profit_pct=AUTO_BUY_TAKE_PROFIT_PCT,
        db_path=DB_PATH,
    )
    return True


def enrich_auto_buy_trade_context(candidate: dict[str, Any]) -> None:
    """Attach audit attribution fields before direct auto-buy trade persistence."""
    symbol = str(candidate.get("symbol") or "").upper()
    prediction_score = candidate.get("ml_prediction_score")
    if prediction_score is None and symbol:
        try:
            prediction = PredictionRepository(DB_PATH).serving_prediction_row(_today(), symbol)
        except Exception as exc:
            prediction = None
            candidate["ml_prediction_lookup_error"] = str(exc)
    else:
        prediction = None

    if prediction:
        prediction_score = prediction.get("prediction_score")
        candidate["prediction_score"] = prediction_score
        candidate["prediction_decision"] = "observe_only"
        candidate["prediction_reason"] = prediction.get("reason")
        candidate["ml_prediction_score"] = prediction_score
        candidate["ml_prediction_confidence"] = prediction.get("confidence")
        candidate["ml_prediction_sample_size"] = prediction.get("sample_size")
        candidate["ml_prediction_generated_at"] = prediction.get("prediction_generated_at")
    elif prediction_score is not None:
        candidate["prediction_score"] = candidate.get("prediction_score") or prediction_score
        candidate["prediction_decision"] = candidate.get("prediction_decision") or "observe_only"

    candidate["ml_prediction_bucket"] = ml_prediction_bucket(prediction_score)
    candidate["effective_size_cap_pct"] = AUTO_BUY_POSITION_SIZE_PCT
    candidate["dominant_limiter"] = "auto_buy_fixed_size"
    candidate["session_momentum_severity"] = (
        "pass"
        if candidate.get("session_trend_label") in {"strong_uptrend", "developing_uptrend"}
        else "observe"
    )


def maybe_execute_auto_buy(candidate: dict[str, Any], market_open: bool, live_requested: bool) -> dict[str, Any] | None:
    if not live_requested or not AUTO_BUY_LIVE_BUYS:
        candidate["live_block_reason"] = "live not requested or AUTO_BUY_LIVE_BUYS is false"
        return None
    if not market_open:
        candidate["live_block_reason"] = "market is closed"
        return None
    if candidate.get("decision") != "strong_buy_candidate":
        candidate["live_block_reason"] = f"decision={candidate.get('decision')}"
        return None
    if (
        candidate.get("signal_source") == "tradingview_alert"
        and tradingview_webhook_required_for_execution()
    ):
        candidate["live_block_reason"] = (
            "tradingview alert symbol requires webhook approval path"
        )
        return None

    capacity_ok, capacity_reason = auto_buy_capacity_check()
    candidate["auto_buy_capacity_reason"] = capacity_reason
    if not capacity_ok:
        candidate["live_block_reason"] = capacity_reason
        return None

    cooldown_active, cooldown_reason = recently_auto_bought(candidate["symbol"])
    if cooldown_active:
        candidate["live_block_reason"] = cooldown_reason
        return None

    risk_ok, risk_reason, risk_details = risk_cross_check(candidate["symbol"])
    candidate["risk_cross_check_reason"] = risk_reason
    candidate["risk_cross_check"] = risk_details
    if not risk_ok:
        candidate["live_block_reason"] = risk_reason
        return None

    from services.broker_service import broker_service

    order = broker_service.place_order(
        symbol=candidate["symbol"],
        action="buy",
        position_size_pct=AUTO_BUY_POSITION_SIZE_PCT,
        stop_loss_pct=AUTO_BUY_STOP_LOSS_PCT,
        take_profit_pct=AUTO_BUY_TAKE_PROFIT_PCT,
        risk_level=candidate.get("risk_level"),
        client_order_id=client_order_id(candidate["symbol"]),
    )
    if not order:
        failure_reason = broker_service.last_order_failure_reason()
        candidate["broker_failure_reason"] = failure_reason
        candidate["live_block_reason"] = (
            "broker returned no order"
            + (f": {failure_reason}" if failure_reason else ": unknown")
        )
    else:
        try:
            log_auto_buy_order(candidate, order)
        except Exception as e:
            candidate["auto_buy_trade_log_error"] = str(e)
        write_app_buy_cooldown(candidate["symbol"])
    return order


def symbols_for_scope(scope: str) -> list[str]:
    if scope == "all":
        return APPROVED_SYMBOLS_LIST
    if scope == "tradingview":
        return [s for s in APPROVED_SYMBOLS_LIST if SYMBOL_SIGNAL_SOURCE.get(s) == "tradingview_alert"]
    return INTERNAL_BAR_ONLY_SYMBOLS_LIST


AUTO_BUY_MAX_SIGNALS_PER_SYMBOL = int(os.getenv("AUTO_BUY_MAX_SIGNALS_PER_SYMBOL", "2"))

AUTO_BUY_BUCKING_TAPE_MIN_SESSION_RETURN_PCT = float(
    os.getenv("AUTO_BUY_BUCKING_TAPE_MIN_SESSION_RETURN_PCT", "2.0")
)
AUTO_BUY_BUCKING_TAPE_MIN_RELATIVE_STRENGTH = float(
    os.getenv("AUTO_BUY_BUCKING_TAPE_MIN_RELATIVE_STRENGTH", "0.30")
)
AUTO_BUY_BUCKING_TAPE_MIN_ACCEL_PCT = float(
    os.getenv("AUTO_BUY_BUCKING_TAPE_MIN_ACCEL_PCT", "0.04")
)
AUTO_BUY_BUCKING_TAPE_MIN_VOLUME_RATIO = float(
    os.getenv("AUTO_BUY_BUCKING_TAPE_MIN_VOLUME_RATIO", "1.8")
)
AUTO_BUY_BUCKING_TAPE_MIN_EARLY_SESSION_RETURN_PCT = float(
    os.getenv("AUTO_BUY_BUCKING_TAPE_MIN_EARLY_SESSION_RETURN_PCT", "0.75")
)


def build_candidates(scope: str) -> list[dict[str, Any]]:
    ctx = load_market_context()
    symbols_ctx = ctx.get("symbols") or {}
    rolling_context = load_rolling_momentum_context()
    intraday_feedback_evidence = (
        intraday_feedback_service().build_evidence(_today())
        if AUTO_BUY_INTRADAY_FEEDBACK_ENABLED
        else {}
    )
    held = held_symbols()
    candidates = []

    # Market-level session gate: if the broad market (QQQ/SPY) is fading or in
    # downtrend, cap all candidates at 'watch' regardless of individual scores.
    mkt_label, mkt_reason = market_session_label()
    market_suppressed = mkt_label in SUPPRESSED_LABELS

    for symbol in symbols_for_scope(scope):
        candidate = evaluate_auto_buy_candidate(
            symbol=symbol,
            session=latest_session(symbol),
            feature=latest_feature(symbol),
            context=symbols_ctx.get(symbol) or {},
            rolling_context=rolling_context.get(symbol.upper()) or {},
            intraday_feedback_evidence=intraday_feedback_evidence,
            held=held,
            signal_source=SYMBOL_SIGNAL_SOURCE.get(symbol, "unknown"),
        )

        # Downgrade strong_buy_candidate → watch when market session is suppressed.
        if market_suppressed and candidate.get("decision") == "strong_buy_candidate":
            candidate["decision"] = "watch"
            candidate["severity"] = "medium"
            candidate["hard_block_reason"] = (
                (candidate.get("hard_block_reason") or "")
                + f"; session_momentum_gate: {mkt_reason}={mkt_label}"
            ).lstrip("; ")

        # Per-symbol daily signal cap: if this symbol has already fired
        # strong_buy_candidate twice today without a filled order, suppress it.
        if candidate.get("decision") == "strong_buy_candidate":
            prior_signals = strong_buy_signals_today(symbol)
            if prior_signals >= AUTO_BUY_MAX_SIGNALS_PER_SYMBOL:
                candidate["decision"] = "skip"
                candidate["severity"] = "low"
                candidate["hard_block_reason"] = (
                    (candidate.get("hard_block_reason") or "")
                    + f"; daily_signal_cap: {prior_signals}>={AUTO_BUY_MAX_SIGNALS_PER_SYMBOL} unfilled signals today"
                ).lstrip("; ")

        candidates.append(candidate)

    candidates.sort(key=lambda item: (item.get("score") or 0), reverse=True)
    return candidates


def render(candidates: list[dict[str, Any]], scope: str, market_open: bool) -> None:
    print("=" * 112)
    print("  Auto-Buy Candidate Manager")
    print("=" * 112)
    print(f"  scope          : {scope}")
    print(f"  market_open    : {market_open}")
    print(f"  live_buy_flag  : {AUTO_BUY_LIVE_BUYS}")
    print(
        "  signal_mode    : "
        f"{'internal_all' if internal_signal_execution_enabled() else 'legacy_source_gate'}"
    )
    print(f"  webhook_required: {tradingview_webhook_required_for_execution()}")
    print(f"  min_score      : {AUTO_BUY_MIN_SCORE}")
    print(f"  active_cap     : {AUTO_BUY_MAX_ACTIVE_POSITIONS}")
    print(f"  daily_gross_cap: {AUTO_BUY_MAX_DAILY_ORDERS}")
    print(f"  cooldown_min   : {AUTO_BUY_COOLDOWN_MINUTES}")
    print()
    print(
        f"{'Sym':<6} {'Source':<18} {'Decision':<22} {'Score':>6} "
        f"{'Session':<20} {'5d':>7} {'Pattern':<30} {'Setup':<30} Reason"
    )
    print("-" * 156)
    for c in candidates:
        five_day = _to_float(c.get("five_day_return_pct"))
        five_day_text = "-" if five_day is None else f"{five_day:+.1f}%"
        print(
            f"{c['symbol']:<6} {c.get('signal_source', '-'):<18} "
            f"{c['decision']:<22} {c['score']:>6.1f} "
            f"{str(c.get('session_trend_label')) + '/' + str(c.get('session_trend_score')):<20} "
            f"{five_day_text:>7} "
            f"{str(c.get('symbol_pattern') or '-')[:30]:<30} "
            f"{str(c.get('setup_label') or '-')[:30]:<30} "
            f"{c.get('hard_block_reason') or c.get('reason')}"
        )


def main() -> int:
    if __name__ == "__main__":
        reexec_under_venv_if_available()

    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("internal", "tradingview", "all"), default="internal")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--live", action="store_true", help="Submit paper buys only if AUTO_BUY_LIVE_BUYS=true")
    args = parser.parse_args()

    init_auto_buy_table()
    now = now_et()
    market_open = is_market_hours(now)
    should_collect, collect_reason = should_collect_candidates(now)
    if not should_collect:
        print("=" * 112)
        print("  Auto-Buy Candidate Manager")
        print("=" * 112)
        print(f"  skipped        : {collect_reason}")
        print("  rows_written   : 0")
        return 0

    candidates = build_candidates(args.scope)

    submitted = 0
    for candidate in candidates:
        order = None
        if submitted < AUTO_BUY_MAX_ORDERS_PER_RUN:
            order = maybe_execute_auto_buy(candidate, market_open=market_open, live_requested=args.live)
            if order:
                submitted += 1
        else:
            candidate["live_block_reason"] = (
                f"per-run auto-buy order cap reached: "
                f"{submitted} >= {AUTO_BUY_MAX_ORDERS_PER_RUN}"
            )

        log_candidate(candidate, live_buy_enabled=args.live and AUTO_BUY_LIVE_BUYS, order=order)
        log_event(
            event_type="AUTO_BUY_CANDIDATE",
            symbol=candidate.get("symbol"),
            action="buy_candidate",
            decision=candidate.get("decision"),
            severity=candidate.get("severity"),
            reason=candidate.get("reason"),
            source="auto_buy_manager.py",
            payload={"candidate": candidate, "order": order},
        )

    if args.json:
        print(json.dumps(candidates, indent=2, sort_keys=True, default=str))
    else:
        render(candidates, args.scope, market_open)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
