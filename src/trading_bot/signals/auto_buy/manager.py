#!/usr/bin/env python3
"""
Internal auto-buy candidate manager.

This is the buy-side sibling to the position momentum auto-sell workflow:
- observe-only by default,
- uses Alpaca-derived session momentum and live feature snapshots,
- records candidate decisions for later comparison against TradingView alerts,
- captures candidate-discovery rows only. Order routing is delegated to the
  canonical signal path, not auto-buy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from bisect import bisect_right
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
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

    os.execv(
        str(VENV_PYTHON),
        [str(VENV_PYTHON), str(BASE_DIR / "scripts" / "auto_buy_manager.py")] + sys.argv[1:],
    )


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
from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository
from repositories.candidate_universe_repo import CandidateUniverseRepository
from repositories.prediction_repo import PredictionRepository
from runtime_config import is_cash_mode
from services.ai_momentum_pattern_service import deterministic_momentum_pattern
from services.broker_service import get_default_broker_service
from services.decision import CapitalAllocator, DecisionEngine
from services.decision.adapters import auto_buy_candidate_from_raw
from services.discovery_execution_bridge_service import (
    DiscoveryExecutionBridgeService,
    bridge_config_from_env,
    bridge_enabled_from_env,
)
from services.historical_bar_model_intelligence_service import (
    build_historical_bar_model_intelligence,
)
from services.historical_bar_paper_strategy_service import build_historical_bar_paper_strategy
from services.intelligence.candidates.reference import candidate_reference_service
from services.intelligence.candidates.universe import CandidateUniverseService
from services.intraday_trade_feedback_service import (
    IntradayTradeFeedbackService,
    build_default_intraday_trade_feedback_service,
)
from services.layered_model_decision_service import build_layered_model_decision
from services.learned_auto_buy_tiebreaker_service import (
    LearnedAutoBuyThresholds,
    LearnedAutoBuyTiebreakerService,
)
from services.policies.entry_policy import ml_prediction_bucket
from strategy_memory import memory_for_signal
from symbols_config import (
    APPROVED_SYMBOLS_LIST,
    CLUSTER_EXPOSURE_LIMITS,
    CORRELATION_CLUSTERS,
    INTERNAL_BAR_ONLY_SYMBOLS_LIST,
    SYMBOL_SIGNAL_SOURCE,
)

from config.conviction import load_conviction_config
from repositories import auto_buy_repo
from risk.exposure import any_cluster_limit_hit, cluster_exposure

_candidate_universe_service = CandidateUniverseService(CandidateUniverseRepository(DB_PATH))

AUTO_BUY_LIVE_BUYS = os.getenv("AUTO_BUY_LIVE_BUYS", "false").lower() in ("1", "true", "yes", "on")
AUTO_BUY_ALLOW_TRADINGVIEW_LIVE = os.getenv("AUTO_BUY_ALLOW_TRADINGVIEW_LIVE", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
AUTO_BUY_SIGNAL_MODE = os.getenv("AUTO_BUY_SIGNAL_MODE", "legacy_source_gate").strip().lower()
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
CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY = int(
    os.getenv("CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY", "1")
)
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
AUTO_BUY_LEARNED_TIEBREAKER_MAX_HISTORICAL_ROWS = int(
    os.getenv("AUTO_BUY_LEARNED_TIEBREAKER_MAX_HISTORICAL_ROWS", "2000")
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
AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED = os.getenv(
    "AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED",
    _paper_runtime_default("true", "false"),
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_PAPER_STRONG_EVIDENCE_SCORE_BUFFER = float(
    os.getenv("AUTO_BUY_PAPER_STRONG_EVIDENCE_SCORE_BUFFER", "3.0")
)
AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SETUP_SCORE = float(
    os.getenv("AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SETUP_SCORE", "50.0")
)
AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_ML_SCORE = float(
    os.getenv("AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_ML_SCORE", "50.0")
)
AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SESSION_SCORE = float(
    os.getenv("AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SESSION_SCORE", "5.0")
)
AUTO_BUY_PAPER_EXPLORATION_FALLBACK_ENABLED = os.getenv(
    "AUTO_BUY_PAPER_EXPLORATION_FALLBACK_ENABLED",
    _paper_runtime_default("true", "false"),
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_PAPER_EXPLORATION_MIN_SCORE = float(
    os.getenv("AUTO_BUY_PAPER_EXPLORATION_MIN_SCORE", "10.0")
)
AUTO_BUY_PAPER_EXPLORATION_MIN_SETUP_SCORE = float(
    os.getenv("AUTO_BUY_PAPER_EXPLORATION_MIN_SETUP_SCORE", "50.0")
)
AUTO_BUY_PAPER_EXPLORATION_MIN_SESSION_SCORE = float(
    os.getenv("AUTO_BUY_PAPER_EXPLORATION_MIN_SESSION_SCORE", "5.0")
)
AUTO_BUY_PAPER_EXPLORATION_MIN_ML_SCORE = float(
    os.getenv("AUTO_BUY_PAPER_EXPLORATION_MIN_ML_SCORE", "50.0")
)
AUTO_BUY_LAYERED_ML_ENABLED = os.getenv(
    "AUTO_BUY_LAYERED_ML_ENABLED",
    _paper_runtime_default("true", "false"),
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED = os.getenv(
    "AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED",
    _paper_runtime_default("true", "false"),
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_LAYERED_ML_VETO_HARD_BLOCK_ENABLED = os.getenv(
    "AUTO_BUY_LAYERED_ML_VETO_HARD_BLOCK_ENABLED",
    _paper_runtime_default("true", "false"),
).strip().lower() in ("1", "true", "yes", "on")
AUTO_BUY_LAYERED_ML_MIN_PROMOTION_CONFIDENCE = float(
    os.getenv("AUTO_BUY_LAYERED_ML_MIN_PROMOTION_CONFIDENCE", "65.0")
)
AUTO_BUY_LAYERED_ML_MIN_VETO_CONFIDENCE = float(
    os.getenv("AUTO_BUY_LAYERED_ML_MIN_VETO_CONFIDENCE", "55.0")
)
AUTO_BUY_LAYERED_ML_SCORE_BOOST = float(os.getenv("AUTO_BUY_LAYERED_ML_SCORE_BOOST", "3.0"))
AUTO_BUY_LAYERED_ML_PASS_SCORE_BOOST = float(
    os.getenv("AUTO_BUY_LAYERED_ML_PASS_SCORE_BOOST", "1.0")
)
AUTO_BUY_LAYERED_ML_WATCH_SCORE_PENALTY = float(
    os.getenv("AUTO_BUY_LAYERED_ML_WATCH_SCORE_PENALTY", "2.0")
)
AUTO_BUY_LAYERED_ML_VETO_SCORE_PENALTY = float(
    os.getenv("AUTO_BUY_LAYERED_ML_VETO_SCORE_PENALTY", "8.0")
)
AUTO_BUY_LAYERED_ML_MAX_THRESHOLD_GAP = float(
    os.getenv("AUTO_BUY_LAYERED_ML_MAX_THRESHOLD_GAP", "6.0")
)
LEARNED_TIEBREAKER_SOFT_BLOCK_PREFIXES = (
    "bias_avoid",
    "setup_avoid",
    "negative_session",
    "15m_falling",
    "30m_falling",
    "ml_prediction_weak",
    "ml_prediction_weak_bucket",
    "strategy_memory_avoid_weak_evidence",
)
PAPER_STRONG_EVIDENCE_SOFT_BLOCK_PREFIXES = (
    "setup_avoid",
    "strategy_memory_avoid_weak_evidence",
)

_prediction_context_cache: dict[str, dict[str, Any]] = {}
_prediction_probability_distribution_cache: dict[tuple[str, str], list[float]] = {}
_learned_tiebreaker_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_rolling_momentum_context_cache: dict[str, dict[str, Any]] | None = None
_intraday_feedback_service: IntradayTradeFeedbackService | None = None
_learned_tiebreaker_service: LearnedAutoBuyTiebreakerService | None = None
_bar_pattern_feature_repo: BarPatternFeatureRepository | None = None
_historical_bar_intelligence_cache: dict[str, Any] | None = None
_initialized_auto_buy_db_paths: set[str] = set()


def intraday_feedback_service() -> IntradayTradeFeedbackService:
    global _intraday_feedback_service
    if _intraday_feedback_service is None:
        _intraday_feedback_service = build_default_intraday_trade_feedback_service(DB_PATH)
    return _intraday_feedback_service


def bar_pattern_feature_repo() -> BarPatternFeatureRepository:
    global _bar_pattern_feature_repo
    if _bar_pattern_feature_repo is None:
        _bar_pattern_feature_repo = BarPatternFeatureRepository(DB_PATH)
    return _bar_pattern_feature_repo


def learned_auto_buy_tiebreaker_service() -> LearnedAutoBuyTiebreakerService:
    global _learned_tiebreaker_service
    if _learned_tiebreaker_service is None:
        thresholds = LearnedAutoBuyThresholds(
            min_sample_size=AUTO_BUY_LEARNED_TIEBREAKER_MIN_SAMPLE_SIZE,
            min_win_rate=AUTO_BUY_LEARNED_TIEBREAKER_MIN_WIN_RATE,
            min_avg_return_pct=AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_RETURN_PCT,
            min_avg_mfe_pct=AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_MFE_PCT,
            max_avg_mae_pct=AUTO_BUY_LEARNED_TIEBREAKER_MAX_AVG_MAE_PCT,
            lookback_days=AUTO_BUY_LEARNED_TIEBREAKER_LOOKBACK_DAYS,
            max_historical_rows=AUTO_BUY_LEARNED_TIEBREAKER_MAX_HISTORICAL_ROWS,
        )
        _learned_tiebreaker_service = LearnedAutoBuyTiebreakerService(
            CandidateUniverseRepository(DB_PATH),
            thresholds,
        )
    return _learned_tiebreaker_service


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _probability_pct(value: Any) -> float | None:
    parsed = _to_float(value)
    if parsed is None:
        return None
    return parsed * 100.0 if 0.0 <= parsed <= 1.0 else parsed


def _first_probability_pct(*values: Any) -> float | None:
    for value in values:
        probability = _probability_pct(value)
        if probability is not None:
            return probability
    return None


def _first_probability_pct_with_source(*items: tuple[str, Any]) -> tuple[float | None, str | None]:
    for source, value in items:
        probability = _probability_pct(value)
        if probability is not None:
            return probability, source
    return None, None


def _probability_family(probability_source: Any) -> str:
    normalized = str(probability_source or "").strip().lower()
    if "probability_of_approval" in normalized:
        return "probability_of_approval"
    if "probability_of_order" in normalized:
        return "probability_of_order"
    return "probability_of_profit"


def _prediction_probability_distribution(family: str) -> list[float]:
    family = _probability_family(family)
    cache_key = (_today(), family)
    cached = _prediction_probability_distribution_cache.get(cache_key)
    if cached is not None:
        return cached
    values: list[float] = []
    try:
        rows = PredictionRepository(DB_PATH).daily_predictions(_today())
    except Exception:
        rows = []
    for row in rows:
        probability = _probability_pct(row.get(family))
        if probability is not None:
            values.append(probability)
    values.sort()
    _prediction_probability_distribution_cache[cache_key] = values
    return values


def _prediction_probability_percentile(
    probability_pct: Any,
    probability_source: Any,
) -> tuple[float | None, int]:
    probability = _probability_pct(probability_pct)
    if probability is None:
        return None, 0
    distribution = _prediction_probability_distribution(_probability_family(probability_source))
    if not distribution:
        return None, 0
    percentile = bisect_right(distribution, probability) / len(distribution) * 100.0
    return round(percentile, 4), len(distribution)


def _historical_bar_intelligence() -> dict[str, Any]:
    global _historical_bar_intelligence_cache
    if _historical_bar_intelligence_cache is None:
        _historical_bar_intelligence_cache = build_historical_bar_model_intelligence()
    return _historical_bar_intelligence_cache


def latest_bar_pattern_features(symbol: str, feature: dict[str, Any]) -> dict[str, Any]:
    """Load the latest ML-trained bar-pattern row and merge live feature hints."""
    row: dict[str, Any] = {}
    for timeframe in ("1Min", "1m"):
        try:
            latest = bar_pattern_feature_repo().latest_for_symbol(symbol, timeframe=timeframe)
        except Exception as exc:
            return {
                "symbol": symbol,
                "status": "lookup_error",
                "lookup_error": str(exc),
                **_dict(feature),
            }
        if latest:
            row = dict(latest)
            break

    feature_payload = _dict(feature)
    merged = {**row, **feature_payload}
    merged.setdefault("symbol", symbol)
    if not row:
        merged["status"] = "missing_latest_bar_pattern_row"
    return merged


def auto_buy_layered_ml_context(
    *,
    symbol: str,
    session: dict[str, Any],
    feature: dict[str, Any],
    context: dict[str, Any],
    prediction_context: dict[str, Any],
    score: float,
    strong_threshold: float | None = None,
    bar_pattern_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Level 0-3 intelligence decision used to influence auto-buy."""
    if not AUTO_BUY_LAYERED_ML_ENABLED:
        return {
            "enabled": False,
            "available": False,
            "runtime_effect": "disabled",
            "reason": "AUTO_BUY_LAYERED_ML_ENABLED=false",
        }

    try:
        bar_features = bar_pattern_features or latest_bar_pattern_features(symbol, feature)
        intelligence = _historical_bar_intelligence()
        account_state = {
            "symbol": symbol,
            "action": "buy",
            "position_size_pct": AUTO_BUY_POSITION_SIZE_PCT,
            "bar_pattern_features": bar_features,
            "microstructure_features": bar_features,
            "historical_bar_model_intelligence": intelligence,
            "prediction_gate": {
                **prediction_context,
                "prediction_score": prediction_context.get("ml_prediction_score"),
                "prediction_decision": prediction_context.get("ml_prediction_bucket"),
            },
            "setup_quality": {
                "score": feature.get("setup_score"),
                "recommendation": feature.get("setup_recommendation"),
                "label": feature.get("setup_label"),
            },
            "buy_opportunity": {
                "buy_opportunity_score": score,
                "buy_opportunity_recommendation": "auto_buy_candidate_scoring",
                "threshold": strong_threshold,
            },
            "session_momentum_gate": {
                "trend_label": session.get("trend_label"),
                "trend_score": session.get("trend_score"),
                "momentum_5m_pct": session.get("momentum_5m_pct"),
                "momentum_15m_pct": session.get("momentum_15m_pct"),
                "momentum_30m_pct": session.get("momentum_30m_pct"),
                "session_return_pct": session.get("session_return_pct"),
                "distance_from_vwap_pct": session.get("distance_from_vwap_pct"),
            },
            "market_context": context,
            "decision_utility": {
                "prob_favorable_move": prediction_context.get("ml_prediction_score"),
            },
        }
        paper_strategy = build_historical_bar_paper_strategy(
            symbol=symbol,
            action="buy",
            account_state=account_state,
            historical_bar_intelligence=intelligence,
            feature_repo=bar_pattern_feature_repo(),
        ).to_dict()
        account_state["historical_bar_paper_strategy"] = paper_strategy
        layered = build_layered_model_decision(
            symbol=symbol,
            action="buy",
            decision={
                "approved": False,
                "position_size_pct": AUTO_BUY_POSITION_SIZE_PCT,
                "confidence": "auto_buy_candidate_scoring",
            },
            account_state=account_state,
            execution_mode="paper" if not is_cash_mode() else "cash",
            ml_authority_config={
                "historical_bar_meta_label_authority": {
                    "enabled": True,
                    "lazy_build_strategy": False,
                    "can_veto": True,
                    "min_veto_score": AUTO_BUY_LAYERED_ML_MIN_VETO_CONFIDENCE,
                    "min_approve_score": AUTO_BUY_LAYERED_ML_MIN_PROMOTION_CONFIDENCE,
                    "min_size_increase_score": max(
                        AUTO_BUY_LAYERED_ML_MIN_PROMOTION_CONFIDENCE + 10.0,
                        75.0,
                    ),
                    "max_position_size_pct": AUTO_BUY_POSITION_SIZE_PCT,
                    "severe_liquidity_blocks": True,
                }
            },
        ).to_dict()
        ensemble = _dict(layered.get("level_1_expert_ensemble"))
        meta = _dict(layered.get("level_2_meta_label"))
        return {
            "enabled": True,
            "available": True,
            "runtime_effect": "paper_bounded_auto_buy_intelligence_authority",
            "final_instruction": layered.get("final_instruction"),
            "final_size_pct": layered.get("final_size_pct"),
            "ensemble_probability_pct": _probability_pct(ensemble.get("ensemble_probability")),
            "meta_label_effect": meta.get("effect"),
            "meta_label_instruction": meta.get("instruction"),
            "master_confidence_score": paper_strategy.get("master_confidence_score"),
            "paper_recommendation": paper_strategy.get("paper_recommendation"),
            "reason": "; ".join(str(item) for item in (layered.get("reasons") or [])[:4]),
            "decision": layered,
            "historical_bar_paper_strategy": paper_strategy,
            "bar_pattern_features": bar_features,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "available": False,
            "runtime_effect": "lookup_error_observe_only",
            "reason": str(exc),
        }


def skipped_auto_buy_layered_ml_context(reason: str) -> dict[str, Any]:
    return {
        "enabled": bool(AUTO_BUY_LAYERED_ML_ENABLED),
        "available": False,
        "runtime_effect": "skipped_hot_path_no_decision_authority",
        "reason": reason,
    }


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


def paper_strong_evidence_soft_block_only(block_reasons: list[str]) -> bool:
    if not block_reasons:
        return True
    for reason in block_reasons:
        if not str(reason).startswith(PAPER_STRONG_EVIDENCE_SOFT_BLOCK_PREFIXES):
            return False
    return True


def strategy_memory_avoid_has_weak_evidence(strategy_memory: dict[str, Any]) -> bool:
    """Treat thin/no-memory avoid lessons as paper-soft, not execution-hard.

    Strategy memory can inherit an avoid recommendation from adjacent/contextual
    matches even when the traded symbol has no closed-trade evidence or only a
    tiny sample. Hard-blocking those cases in paper mode prevents the platform
    from collecting the forward evidence needed to prove or reject the lesson.
    """
    reason = str(strategy_memory.get("reason") or "").strip().lower()
    if "no symbol memory" in reason or "sample too small" in reason:
        return True

    symbol_memory = strategy_memory.get("symbol_memory") or {}
    try:
        trades = int(float(symbol_memory.get("trades") or 0))
    except (TypeError, ValueError):
        trades = 0
    return trades < 3


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
        profit_source = row.get("probability_of_profit_source")
        probability_profit_source = (
            f"probability_of_profit:{profit_source}" if profit_source else "probability_of_profit"
        )
        probability_pct, probability_source = _first_probability_pct_with_source(
            (probability_profit_source, row.get("probability_of_profit")),
            ("probability_of_approval", row.get("probability_of_approval")),
            ("probability_of_order", row.get("probability_of_order")),
        )
        probability_percentile_pct, probability_distribution_size = (
            _prediction_probability_percentile(probability_pct, probability_source)
        )
        result.update(
            {
                "available": True,
                "prediction_score": score,
                "prediction_decision": "observe_only",
                "prediction_reason": row.get("reason"),
                "probability_of_profit": row.get("probability_of_profit"),
                "probability_of_profit_source": profit_source,
                "probability_of_profit_sample_size": row.get("probability_of_profit_sample_size"),
                "probability_of_approval": row.get("probability_of_approval"),
                "probability_of_order": row.get("probability_of_order"),
                "probability_of_profit_pct": _probability_pct(row.get("probability_of_profit")),
                "probability_of_approval_pct": _probability_pct(row.get("probability_of_approval")),
                "probability_of_order_pct": _probability_pct(row.get("probability_of_order")),
                "probability_pct": probability_pct,
                "probability_source": probability_source,
                "probability_percentile_pct": probability_percentile_pct,
                "probability_distribution_size": probability_distribution_size,
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
        result = (
            {
                str(symbol).upper(): dict(payload)
                for symbol, payload in symbols.items()
                if isinstance(payload, dict)
            }
            if isinstance(symbols, dict)
            else {}
        )

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
    decision = learned_auto_buy_tiebreaker_service().decide(candidate, target_date=target_date)
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
    try:
        auto_buy_repo.init_tables(DB_PATH)
    except Exception as exc:
        if not auto_buy_repo.is_database_locked_error(exc):
            raise
        print(
            "auto_buy table initialization skipped: database is locked; "
            "assuming migrated production schema is already present"
        )
    _initialized_auto_buy_db_paths.add(str(DB_PATH))


def ensure_auto_buy_tables_initialized() -> None:
    db_key = str(DB_PATH)
    if db_key in _initialized_auto_buy_db_paths:
        return
    init_auto_buy_table()


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


def recently_auto_bought(
    symbol: str, cooldown_minutes: int = AUTO_BUY_COOLDOWN_MINUTES
) -> tuple[bool, str]:
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


def app_buy_cooldown_active(
    symbol: str, cooldown_minutes: int = APP_BUY_COOLDOWN_MINUTES
) -> tuple[bool, str]:
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


def recent_sell_active(
    symbol: str, cooldown_minutes: int = APP_RECENT_SELL_COOLDOWN_MINUTES
) -> tuple[bool, str]:
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
        positions.append(
            {
                "symbol": p.symbol.upper(),
                "qty": getattr(p, "qty", None),
                "current_price": getattr(p, "current_price", None),
                "market_value": getattr(p, "market_value", None),
            }
        )
    account = broker_service.get_account() or {}
    balance = _to_float(account.get("balance"), 0) or 0.0
    return positions, balance


def risk_cross_check(symbol: str) -> tuple[bool, str, dict[str, Any]]:
    if (
        is_cash_mode()
        and app_approved_buys_today(symbol) >= CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY
    ):
        return (
            False,
            (
                f"app daily symbol buy limit reached: buys_today>="
                f"{CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY}"
            ),
            {},
        )

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
        return (
            False,
            (
                f"correlation cap: {hit['cluster']} exposure "
                f"{hit['exposure_pct']:.2f}% >= {hit['limit_pct']:.2f}%"
            ),
            {"correlation_exposure": cluster_checks},
        )

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
        momentum_state = (
            "accelerating"
            if acceleration >= 0.03
            else "decelerating"
            if acceleration <= -0.03
            else "mixed"
        )
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
            "participation_state": ("confirmed" if relative_strength >= 0.30 else "not_confirmed"),
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

    def _timed(label: str, phase_started: float) -> float:
        if AUTO_BUY_TIMING_LOG_ENABLED:
            elapsed = time.monotonic() - phase_started
            if elapsed >= 0.25:
                print(
                    f"[TIMING] auto_buy.evaluate.{label} symbol={symbol} elapsed={elapsed:.2f}s",
                    flush=True,
                )
        return time.monotonic()

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
            "evaluation_depth": "short_circuit_held",
            "layered_ml_evaluation_depth": "not_evaluated_held_symbol",
        }

    score = 0.0
    reasons = []

    bias = context.get("bias")
    entry_quality = context.get("entry_quality")
    risk_level = context.get("risk_level")
    avoid_type = context.get("avoid_type")
    webull_market_context = context.get("webull_market_context") or {}
    webull_morning_brief_context = context.get("webull_morning_brief_context") or {}
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
    m60 = _to_float(session.get("momentum_60m_pct"), 0) or 0
    m120 = _to_float(session.get("momentum_120m_pct"), 0) or 0
    trend_regime = str(session.get("trend_regime") or "").strip().lower()
    trend_persistence_score = _to_float(session.get("trend_persistence_score"), 0) or 0
    pullback_with_trend_score = _to_float(session.get("pullback_with_trend_score"), 0) or 0
    late_chase_maturity_score = _to_float(session.get("late_chase_maturity_score"), 0) or 0
    vwap = _to_float(session.get("distance_from_vwap_pct"), 0) or 0
    session_return = _to_float(session.get("session_return_pct"), 0) or 0
    five_day_return = _to_float(rolling_context.get("five_day_return_pct"))
    prior_day_return = _to_float(rolling_context.get("prior_day_return_pct"))
    current_vs_prior_close = _to_float(rolling_context.get("current_price_vs_prior_close_pct"))
    extension_from_recent_base = _to_float(rolling_context.get("extension_from_recent_base_pct"))
    rolling_continuation_score = _to_float(rolling_context.get("continuation_score"))
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

    if m60 > 0.50:
        score += 2
        reasons.append("60m_rising:+2")
    elif m60 < -0.50:
        score -= 2
        reasons.append("60m_falling:-2")

    if m120 > 0.75:
        score += 2
        reasons.append("120m_rising:+2")
    elif m120 < -0.75:
        score -= 2
        reasons.append("120m_falling:-2")

    structural_uptrend = (
        trend_regime in {"persistent_uptrend", "pullback_with_uptrend"}
        or trend_persistence_score >= 3
        or (m60 >= 0.50 and m120 >= 0.50)
        or (session_return >= 0.75 and m60 >= 0.30)
    )
    structural_downtrend = (
        trend_regime == "persistent_downtrend"
        or trend_persistence_score <= -3
        or (m60 <= -0.50 and m120 <= -0.50)
    )
    structural_context_offsets_30m = structural_uptrend and not structural_downtrend
    constructive_pullback = structural_uptrend and (
        trend_regime == "pullback_with_uptrend" or pullback_with_trend_score >= 3
    )

    if trend_regime == "persistent_uptrend":
        score += 2
        reasons.append("structural_uptrend:+2")
    elif trend_regime == "pullback_with_uptrend":
        score += 2
        reasons.append("pullback_with_uptrend:+2")
    elif trend_regime == "persistent_downtrend":
        score -= 3
        reasons.append("structural_downtrend:-3")
    elif trend_regime == "mature_uptrend":
        score -= 1
        reasons.append("mature_uptrend_caution:-1")

    if constructive_pullback and m30 < -0.35:
        score += 1
        reasons.append("constructive_30m_pullback:+1")

    if late_chase_maturity_score >= 3 and session_return >= 1.5:
        score -= 2
        reasons.append(f"late_chase_maturity:-2({late_chase_maturity_score:.0f})")

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
        and setup_label
        not in {
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
        reasons.append(f"mature_chase_extension:-4(session={session_return:.2f}%,vwap={vwap:.2f}%)")

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

    phase_started = time.monotonic()
    bar_pattern_features_for_memory = latest_bar_pattern_features(symbol, feature)
    phase_started = _timed("bar_pattern_features", phase_started)
    strategy_memory = memory_for_signal(
        symbol,
        {
            "bar_pattern_features": bar_pattern_features_for_memory,
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
    phase_started = _timed("strategy_memory", phase_started)
    learned_min_setup_score = strategy_memory.get("min_setup_score")
    memory_rec = str(strategy_memory.get("recommendation") or "none").strip().lower()
    bar_pattern_memory = strategy_memory.get("bar_pattern_evidence") or {}
    strategy_memory_caution_gate = False
    if strategy_memory.get("available"):
        reasons.append(
            "strategy_memory:"
            f"{memory_rec}:min_setup={learned_min_setup_score}:"
            f"trades={((strategy_memory.get('symbol_memory') or {}).get('trades'))}"
        )
        if bar_pattern_memory.get("authority_ready"):
            reasons.append(
                "bar_pattern_memory:"
                f"{bar_pattern_memory.get('active_recommendation')}:"
                f"{bar_pattern_memory.get('matched_pattern_label') or 'no_label'}:"
                f"{bar_pattern_memory.get('matched_opportunity_key') or 'no_opportunity'}"
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

    hard_block_reasons = []

    volume_ratio = _to_float(feature.get("volume_ratio_5m"), 0) or 0
    prediction_context = auto_buy_prediction_context(symbol)
    phase_started = _timed("prediction_context", phase_started)
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
        memory_avoid_reason = (
            f"setup_score={setup_score:.1f}<learned_min={learned_min_setup_score};"
            f"{strategy_memory.get('reason')}"
        )
        if not is_cash_mode() and strategy_memory_avoid_has_weak_evidence(strategy_memory):
            hard_block_reasons.append(f"strategy_memory_avoid_weak_evidence:{memory_avoid_reason}")
        else:
            hard_block_reasons.append(f"strategy_memory_avoid:{memory_avoid_reason}")
    if label in ("downtrend", "fading"):
        if not bucking_negative_tape and not structural_context_offsets_30m:
            hard_block_reasons.append(f"negative_session:{label}")
        elif structural_context_offsets_30m:
            reasons.append(f"negative_session_soft_structural_context:{label}")
    if m15 < -0.20:
        if not bucking_negative_tape:
            hard_block_reasons.append(f"15m_falling:{m15:.3f}")
        else:
            reasons.append(f"15m_falling_soft:{m15:.3f}")
    if m30 < -0.35:
        if not bucking_negative_tape and not structural_context_offsets_30m:
            hard_block_reasons.append(f"30m_falling:{m30:.3f}")
        elif structural_context_offsets_30m:
            reasons.append(f"30m_falling_soft_structural_context:{m30:.3f}")
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
    phase_started = _timed("symbol_pattern", phase_started)
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
        phase_started = _timed("intraday_feedback", phase_started)
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

    strong_threshold = AUTO_BUY_MIN_SCORE
    execution_signal_mode = (
        "internal_all" if internal_signal_execution_enabled() else "legacy_source_gate"
    )
    requires_webhook = (
        signal_source == "tradingview_alert" and tradingview_webhook_required_for_execution()
    )
    if requires_webhook:
        strong_threshold = AUTO_BUY_MIN_SCORE + 4.0
        reasons.append(f"webhook_symbol_candidate_threshold:{strong_threshold:.1f}")
    elif signal_source == "tradingview_alert":
        reasons.append(f"internal_signal_execution:{execution_signal_mode}")

    layered_ml_threshold_gap_before_build = round(float(strong_threshold) - float(score), 4)
    layered_ml_veto_relevant = score >= (
        float(strong_threshold) - AUTO_BUY_LAYERED_ML_VETO_SCORE_PENALTY
    )
    layered_ml_promotion_relevant = (
        score + AUTO_BUY_LAYERED_ML_SCORE_BOOST >= AUTO_BUY_WATCH_SCORE
        and layered_ml_threshold_gap_before_build <= AUTO_BUY_LAYERED_ML_MAX_THRESHOLD_GAP
    )
    layered_ml_build_relevant = (
        AUTO_BUY_LAYERED_ML_ENABLED
        and not hard_block_reasons
        and (layered_ml_veto_relevant or layered_ml_promotion_relevant)
    )
    if layered_ml_build_relevant:
        layered_ml_evaluation_depth = "full_layered_ml"
        layered_ml = auto_buy_layered_ml_context(
            symbol=symbol,
            session=session,
            feature=feature,
            context=context,
            prediction_context=prediction_context,
            score=score,
            strong_threshold=strong_threshold,
            bar_pattern_features=bar_pattern_features_for_memory,
        )
    else:
        if not AUTO_BUY_LAYERED_ML_ENABLED:
            skip_reason = "layered_ml_disabled"
            layered_ml_evaluation_depth = "layered_ml_disabled"
        elif hard_block_reasons:
            skip_reason = "hard_block_present"
            layered_ml_evaluation_depth = "shallow_hard_block"
        elif score + AUTO_BUY_LAYERED_ML_SCORE_BOOST < AUTO_BUY_WATCH_SCORE:
            skip_reason = (
                "score_unreachable:"
                f"{score:.2f}+{AUTO_BUY_LAYERED_ML_SCORE_BOOST:.2f}<"
                f"{AUTO_BUY_WATCH_SCORE:.2f}"
            )
            layered_ml_evaluation_depth = "shallow_unreachable_score"
        else:
            skip_reason = (
                f"outside_layered_authority_window:gap={layered_ml_threshold_gap_before_build:.2f}"
            )
            layered_ml_evaluation_depth = "shallow_outside_authority_window"
        layered_ml = skipped_auto_buy_layered_ml_context(skip_reason)
        reasons.append(f"layered_ml_skipped:{skip_reason}")
    layered_ml_available = bool(layered_ml.get("available"))
    layered_instruction = str(layered_ml.get("final_instruction") or "none").strip().lower()
    layered_meta_effect = str(layered_ml.get("meta_label_effect") or "none").strip().lower()
    layered_master_confidence = _to_float(layered_ml.get("master_confidence_score"))
    layered_ensemble_pct = _to_float(layered_ml.get("ensemble_probability_pct"))
    prediction_probability_pct, prediction_probability_source = _first_probability_pct_with_source(
        (
            str(prediction_context.get("probability_source") or "probability_pct"),
            prediction_context.get("probability_pct"),
        ),
        ("probability_of_profit", prediction_context.get("probability_of_profit")),
        ("probability_of_approval", prediction_context.get("probability_of_approval")),
        ("probability_of_order", prediction_context.get("probability_of_order")),
    )
    conviction_probability_pct = layered_ensemble_pct
    conviction_probability_source = "layered_ml_ensemble_probability_pct"
    if conviction_probability_pct is None:
        conviction_probability_pct = prediction_probability_pct
        conviction_probability_source = prediction_probability_source or "daily_symbol_predictions"
    conviction_probability_percentile_pct = None
    conviction_probability_distribution_size = 0
    if (
        conviction_probability_pct is not None
        and conviction_probability_source == prediction_probability_source
    ):
        conviction_probability_percentile_pct = prediction_context.get("probability_percentile_pct")
        conviction_probability_distribution_size = (
            _to_float(prediction_context.get("probability_distribution_size"), 0) or 0
        )

    # Conviction entry uses the deterministic candidate confluence score, not
    # later layered-ML score nudges. Layered ML remains a veto/probability input.
    confluence_score = score
    if layered_ml.get("enabled") and not layered_ml_available:
        reasons.append(f"layered_ml:unavailable:{layered_ml.get('reason')}")
    elif layered_ml_available:
        if layered_instruction == "veto":
            score -= AUTO_BUY_LAYERED_ML_VETO_SCORE_PENALTY
            reasons.append(
                "layered_ml_veto:"
                f"{layered_meta_effect}:{AUTO_BUY_LAYERED_ML_VETO_SCORE_PENALTY:.1f}:"
                f"{layered_ml.get('reason')}"
            )
            if AUTO_BUY_LAYERED_ML_VETO_HARD_BLOCK_ENABLED and not is_cash_mode():
                hard_block_reasons.append(
                    "layered_ml_veto:"
                    f"{layered_meta_effect or layered_instruction}:"
                    f"{layered_ml.get('reason')}"
                )
        elif layered_instruction in {"paper_approval", "size_increase"}:
            score += AUTO_BUY_LAYERED_ML_SCORE_BOOST
            reasons.append(
                "layered_ml_approval:"
                f"{layered_instruction}:+{AUTO_BUY_LAYERED_ML_SCORE_BOOST:.1f}:"
                f"confidence={layered_master_confidence}"
            )
        elif layered_instruction == "pass":
            score += AUTO_BUY_LAYERED_ML_PASS_SCORE_BOOST
            reasons.append(
                "layered_ml_pass:"
                f"+{AUTO_BUY_LAYERED_ML_PASS_SCORE_BOOST:.1f}:"
                f"ensemble={layered_ensemble_pct}"
            )
        elif layered_instruction == "watch":
            score -= AUTO_BUY_LAYERED_ML_WATCH_SCORE_PENALTY
            reasons.append(
                "layered_ml_watch:"
                f"-{AUTO_BUY_LAYERED_ML_WATCH_SCORE_PENALTY:.1f}:"
                f"ensemble={layered_ensemble_pct}"
            )

    hard_block_audit_reasons = list(hard_block_reasons)
    hard_block_audit_reason = (
        "; ".join(hard_block_audit_reasons) if hard_block_audit_reasons else None
    )

    if strategy_memory_caution_gate and score >= AUTO_BUY_WATCH_SCORE:
        hard_block_audit_decision_without_blocks = "watch"
        hard_block_audit_severity_without_blocks = "medium"
    elif score >= strong_threshold and (
        setup_rec != "watch" or AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED
    ):
        hard_block_audit_decision_without_blocks = "strong_buy_candidate"
        hard_block_audit_severity_without_blocks = "high"
    elif score >= AUTO_BUY_WATCH_SCORE:
        hard_block_audit_decision_without_blocks = "watch"
        hard_block_audit_severity_without_blocks = "medium"
    else:
        hard_block_audit_decision_without_blocks = "skip"
        hard_block_audit_severity_without_blocks = "low"

    hard_block_reason = hard_block_audit_reason

    if hard_block_reasons:
        decision = "skip"
        severity = "blocked"
    elif strategy_memory_caution_gate and score >= AUTO_BUY_WATCH_SCORE:
        decision = "watch"
        severity = "medium"
        reasons.append("strategy_memory_caution_caps_at_watch")
    elif score >= strong_threshold and (
        setup_rec != "watch" or AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED
    ):
        decision = "strong_buy_candidate"
        severity = "high"
    elif score >= AUTO_BUY_WATCH_SCORE:
        decision = "watch"
        severity = "medium"
    else:
        decision = "skip"
        severity = "low"

    paper_promotion_applied = False
    paper_promotion_reason = None
    paper_promotion_soft_blocks_only = paper_strong_evidence_soft_block_only(hard_block_reasons)
    ml_score_for_promotion = ml_score if ml_score is not None else 50.0
    paper_promotion_allowed = (
        AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED
        and not is_cash_mode()
        and not requires_webhook
        and decision in {"watch", "skip"}
        and score >= strong_threshold + AUTO_BUY_PAPER_STRONG_EVIDENCE_SCORE_BUFFER
        and paper_promotion_soft_blocks_only
        and setup_score >= AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SETUP_SCORE
        and session_score >= AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SESSION_SCORE
        and m15 > 0
        and m30 > 0
        and not extreme_chase
        and ml_score_for_promotion >= AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_ML_SCORE
        and str(intraday_feedback.get("status") or "neutral") not in {"block", "would_block"}
    )
    if paper_promotion_allowed:
        decision = "strong_buy_candidate"
        severity = "high"
        paper_promotion_applied = True
        if hard_block_reasons:
            hard_block_reason = None
        paper_promotion_reason = (
            "paper_strong_evidence:"
            f"score={score:.2f}>={strong_threshold + AUTO_BUY_PAPER_STRONG_EVIDENCE_SCORE_BUFFER:.2f};"
            f"setup={setup_score:.1f};session={session_score:.1f};"
            f"ml={ml_score_for_promotion:.2f}"
        )
        reasons.append(f"paper_strong_evidence_promoted:{paper_promotion_reason}")

    paper_exploration_fallback_applied = False
    paper_exploration_fallback_reason = None
    paper_exploration_fallback_soft_blocks_only = learned_tiebreaker_soft_block_only(
        hard_block_reasons
    )
    paper_exploration_fallback_allowed = (
        AUTO_BUY_PAPER_EXPLORATION_FALLBACK_ENABLED
        and not is_cash_mode()
        and not requires_webhook
        and decision in {"watch", "skip"}
        and score >= AUTO_BUY_PAPER_EXPLORATION_MIN_SCORE
        and paper_exploration_fallback_soft_blocks_only
        and setup_score >= AUTO_BUY_PAPER_EXPLORATION_MIN_SETUP_SCORE
        and session_score >= AUTO_BUY_PAPER_EXPLORATION_MIN_SESSION_SCORE
        and m15 > 0
        and m30 > 0
        and not extreme_chase
        and ml_score_for_promotion >= AUTO_BUY_PAPER_EXPLORATION_MIN_ML_SCORE
        and str(intraday_feedback.get("status") or "neutral") not in {"block", "would_block"}
    )
    if paper_exploration_fallback_allowed:
        decision = "strong_buy_candidate"
        severity = "high"
        paper_exploration_fallback_applied = True
        if hard_block_reasons:
            hard_block_reason = None
        paper_exploration_fallback_reason = (
            "paper_exploration_fallback:"
            f"score={score:.2f}>={AUTO_BUY_PAPER_EXPLORATION_MIN_SCORE:.2f};"
            f"setup={setup_score:.1f};session={session_score:.1f};"
            f"ml={ml_score_for_promotion:.2f}"
        )
        reasons.append(f"paper_exploration_fallback_promoted:{paper_exploration_fallback_reason}")

    layered_ml_promotion_applied = False
    layered_ml_promotion_reason = None
    layered_ml_threshold_gap = round(float(strong_threshold) - float(score), 4)
    layered_ml_promotion_allowed = (
        AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED
        and layered_ml_available
        and not is_cash_mode()
        and not requires_webhook
        and not hard_block_reasons
        and decision in {"watch", "skip"}
        and score >= AUTO_BUY_WATCH_SCORE
        and layered_ml_threshold_gap <= AUTO_BUY_LAYERED_ML_MAX_THRESHOLD_GAP
        and layered_instruction in {"paper_approval", "size_increase"}
        and (layered_master_confidence or 0.0) >= AUTO_BUY_LAYERED_ML_MIN_PROMOTION_CONFIDENCE
        and (_to_float(layered_ml.get("final_size_pct"), 0) or 0) > 0
        and str(intraday_feedback.get("status") or "neutral") not in {"block", "would_block"}
    )
    if layered_ml_promotion_allowed:
        decision = "strong_buy_candidate"
        severity = "high"
        layered_ml_promotion_applied = True
        layered_ml_promotion_reason = (
            "layered_ml_paper_authority:"
            f"instruction={layered_instruction};"
            f"confidence={layered_master_confidence};"
            f"ensemble={layered_ensemble_pct};"
            f"gap={layered_ml_threshold_gap:.2f}"
        )
        reasons.append(f"layered_ml_promoted:{layered_ml_promotion_reason}")

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
        phase_started = _timed("learned_tiebreaker", phase_started)
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
                f"learned_tiebreaker_promoted:{learned_tiebreaker_reason}:gap={threshold_gap:.2f}"
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
        "confluence_score": round(confluence_score, 2),
        "conviction_score": round(confluence_score, 2),
        "strong_buy_threshold": strong_threshold,
        "reason": "; ".join(reasons) if reasons else "no positive auto-buy evidence",
        "hard_block_reason": hard_block_reason,
        "hard_block_audit_active": bool(hard_block_audit_reasons),
        "hard_block_audit_reason": hard_block_audit_reason,
        "hard_block_audit_reasons": hard_block_audit_reasons,
        "hard_block_audit_reason_count": len(hard_block_audit_reasons),
        "hard_block_audit_decision_without_hard_blocks": (hard_block_audit_decision_without_blocks),
        "hard_block_audit_severity_without_hard_blocks": (hard_block_audit_severity_without_blocks),
        "hard_block_audit_would_be_strong_candidate": (
            hard_block_audit_decision_without_blocks == "strong_buy_candidate"
        ),
        "hard_block_audit_score_gap_to_strong": round(float(score) - float(strong_threshold), 4),
        "hard_block_audit_runtime_effect": ("counterfactual_observation_only_no_trade_authority"),
        "evaluation_depth": layered_ml_evaluation_depth,
        "market_bias": bias,
        "entry_quality": entry_quality,
        "risk_level": risk_level,
        "probability_pct": conviction_probability_pct,
        "probability_source": (
            conviction_probability_source if conviction_probability_pct is not None else None
        ),
        "probability_percentile_pct": conviction_probability_percentile_pct,
        "probability_distribution_size": int(conviction_probability_distribution_size),
        "prediction_probability_pct": prediction_probability_pct,
        "prediction_probability_source": prediction_probability_source,
        "prediction_probability_percentile_pct": prediction_context.get(
            "probability_percentile_pct"
        ),
        "prediction_probability_distribution_size": prediction_context.get(
            "probability_distribution_size"
        ),
        "prediction_probability_of_profit_pct": prediction_context.get("probability_of_profit_pct"),
        "prediction_probability_of_profit_source": prediction_context.get(
            "probability_of_profit_source"
        ),
        "prediction_probability_of_profit_sample_size": prediction_context.get(
            "probability_of_profit_sample_size"
        ),
        "prediction_probability_of_approval_pct": prediction_context.get(
            "probability_of_approval_pct"
        ),
        "prediction_probability_of_order_pct": prediction_context.get("probability_of_order_pct"),
        "webull_market_context": webull_market_context,
        "webull_market_evidence_tags": webull_market_context.get("evidence_tags") or [],
        "webull_market_runtime_effect": webull_market_context.get("runtime_effect"),
        "webull_morning_brief_context": webull_morning_brief_context,
        "webull_morning_brief_runtime_effect": webull_morning_brief_context.get("runtime_effect"),
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
        "rolling_momentum_source": ("rolling_momentum_json" if rolling_context else "missing"),
        "momentum_5m_pct": m5,
        "momentum_15m_pct": m15,
        "momentum_30m_pct": m30,
        "momentum_60m_pct": m60,
        "momentum_120m_pct": m120,
        "trend_regime": trend_regime,
        "trend_persistence_score": trend_persistence_score,
        "pullback_with_trend_score": pullback_with_trend_score,
        "late_chase_maturity_score": late_chase_maturity_score,
        "distance_from_vwap_pct": vwap,
        "setup_label": setup_label,
        "setup_recommendation": setup_rec,
        "setup_score": setup_score,
        "strategy_memory_recommendation": memory_rec,
        "strategy_memory_min_setup_score": learned_min_setup_score,
        "strategy_memory_reason": strategy_memory.get("reason"),
        "strategy_memory_available": bool(strategy_memory.get("available")),
        "strategy_memory_bar_pattern_authority_ready": bool(
            bar_pattern_memory.get("authority_ready")
        ),
        "strategy_memory_bar_pattern_recommendation": (
            bar_pattern_memory.get("active_recommendation")
        ),
        "strategy_memory_bar_pattern_label": bar_pattern_memory.get("matched_pattern_label"),
        "strategy_memory_bar_pattern_opportunity": (
            bar_pattern_memory.get("matched_opportunity_key")
        ),
        "strategy_memory_bar_pattern_runtime_effect": bar_pattern_memory.get("runtime_effect"),
        "strategy_memory_bar_pattern_features": bar_pattern_features_for_memory,
        "paper_strong_evidence_promotion_enabled": bool(
            AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED
        ),
        "paper_strong_evidence_promotion_allowed": bool(paper_promotion_allowed),
        "paper_strong_evidence_promotion_applied": bool(paper_promotion_applied),
        "paper_strong_evidence_promotion_reason": paper_promotion_reason,
        "paper_strong_evidence_soft_blocks_only": bool(paper_promotion_soft_blocks_only),
        "paper_strong_evidence_runtime_effect": (
            "paper_only_auto_buy_promotion"
            if paper_promotion_applied
            else "observe_only_or_not_qualified"
        ),
        "paper_exploration_fallback_enabled": bool(AUTO_BUY_PAPER_EXPLORATION_FALLBACK_ENABLED),
        "paper_exploration_fallback_allowed": bool(paper_exploration_fallback_allowed),
        "paper_exploration_fallback_applied": bool(paper_exploration_fallback_applied),
        "paper_exploration_fallback_reason": paper_exploration_fallback_reason,
        "paper_exploration_fallback_soft_blocks_only": bool(
            paper_exploration_fallback_soft_blocks_only
        ),
        "paper_exploration_fallback_runtime_effect": (
            "bounded_paper_exploration_from_soft_blocks"
            if paper_exploration_fallback_applied
            else "observe_only_or_not_qualified"
        ),
        "layered_ml_enabled": bool(AUTO_BUY_LAYERED_ML_ENABLED),
        "layered_ml_evaluation_depth": layered_ml_evaluation_depth,
        "layered_ml_available": bool(layered_ml_available),
        "layered_ml_runtime_effect": layered_ml.get("runtime_effect"),
        "layered_ml_final_instruction": layered_instruction,
        "layered_ml_final_size_pct": layered_ml.get("final_size_pct"),
        "layered_ml_ensemble_probability_pct": layered_ensemble_pct,
        "layered_ml_meta_label_effect": layered_meta_effect,
        "layered_ml_meta_label_instruction": layered_ml.get("meta_label_instruction"),
        "layered_ml_master_confidence_score": layered_master_confidence,
        "layered_ml_paper_recommendation": layered_ml.get("paper_recommendation"),
        "layered_ml_reason": layered_ml.get("reason"),
        "layered_ml_decision": layered_ml.get("decision") or {},
        "layered_ml_historical_bar_paper_strategy": (
            layered_ml.get("historical_bar_paper_strategy") or {}
        ),
        "layered_ml_bar_pattern_features": layered_ml.get("bar_pattern_features") or {},
        "layered_ml_promotion_enabled": bool(AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED),
        "layered_ml_promotion_allowed": bool(layered_ml_promotion_allowed),
        "layered_ml_promotion_applied": bool(layered_ml_promotion_applied),
        "layered_ml_promotion_reason": layered_ml_promotion_reason,
        "layered_ml_threshold_gap": layered_ml_threshold_gap,
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


def attach_canonical_decision_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    """Attach canonical candidate and decision trace metadata for learning/replay."""
    canonical = auto_buy_candidate_from_raw(candidate)
    approved = candidate.get("decision") == "strong_buy_candidate"
    allocation = CapitalAllocator(max_risk_pct=2.0).allocate(
        requested_size_pct=candidate.get("effective_size_cap_pct") or AUTO_BUY_POSITION_SIZE_PCT,
        confidence="auto_buy_manager" if approved else "low",
        liquidity_stress=candidate.get("liquidity_stress") or candidate.get("lsi_status"),
    )
    account_state = {
        "setup_quality": {
            "score": candidate.get("setup_score"),
            "recommendation": candidate.get("setup_label"),
            "policy_action": candidate.get("setup_policy_action"),
            "reason": candidate.get("setup_policy_reason"),
        },
        "buy_opportunity": {
            "buy_opportunity_score": candidate.get("score"),
            "buy_opportunity_recommendation": candidate.get("decision"),
            "reason": candidate.get("reason") or candidate.get("hard_block_reason"),
            "max_position_size_pct": candidate.get("effective_size_cap_pct"),
        },
        "prediction_gate": {
            "prediction_score": candidate.get("prediction_score")
            or candidate.get("ml_prediction_score"),
            "sample_size": candidate.get("ml_prediction_sample_size"),
            "decision": candidate.get("prediction_decision"),
            "reason": candidate.get("prediction_reason"),
        },
        "session_momentum_gate": {
            "severity": candidate.get("session_momentum_severity"),
            "trend_label": candidate.get("session_trend_label"),
            "trend_score": candidate.get("session_trend_score"),
            "reason": candidate.get("session_momentum_reason"),
        },
        "layered_model_decision": candidate.get("layered_ml_decision") or {},
        "historical_bar_paper_strategy": (
            candidate.get("layered_ml_historical_bar_paper_strategy") or {}
        ),
        "bar_pattern_features": candidate.get("layered_ml_bar_pattern_features") or {},
        "execution_quality": {
            "decision": "allow" if approved else "observe",
            "reason": candidate.get("live_block_reason") or "auto-buy candidate scoring",
        },
        "sizing": {
            "decision": "cap",
            "size_cap_pct": allocation.allocated_size_pct,
            "dominant_limiter": candidate.get("dominant_limiter") or "capital_allocator",
            "capital_allocation": allocation.to_dict(),
        },
    }
    decision = {
        "approved": approved,
        "confidence": "auto_buy_manager",
        "reason": candidate.get("reason") or candidate.get("hard_block_reason") or "",
        "position_size_pct": allocation.allocated_size_pct,
    }
    evaluation = DecisionEngine().store_to_account_state(
        account_state=account_state,
        decision=decision,
        source="auto_buy",
        execution_mode=os.getenv("EXECUTION_MODE", "paper").strip().lower(),
    )
    enriched = dict(candidate)
    enriched["canonical_signal_candidate"] = canonical.to_dict()
    enriched["intelligence_adjudication"] = evaluation.adjudication.to_dict()
    enriched["capital_allocation"] = allocation.to_dict()
    enriched["effective_size_cap_pct"] = allocation.allocated_size_pct
    enriched["decision_trace"] = evaluation.trace.to_dict()
    enriched["canonical_decision_trace"] = enriched["decision_trace"]
    enriched["decision_engine_runtime_effect"] = "canonical_auto_buy_trace_and_authority_metadata"
    return enriched


def log_candidate(
    candidate: dict[str, Any], live_buy_enabled: bool, order: dict[str, Any] | None = None
) -> None:
    order = order or {}
    timestamp = now_et().isoformat()
    candidate = enrich_candidate_with_reference_snapshot(candidate)
    candidate = attach_canonical_decision_metadata(candidate)
    ensure_auto_buy_tables_initialized()
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
        _candidate_universe_service.persist_scored_candidate(
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
        print(
            f"[WARN] candidate universe capture failed for {candidate.get('symbol')}: {exc}",
            file=sys.stderr,
        )


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


def maybe_execute_auto_buy(
    candidate: dict[str, Any], market_open: bool, live_requested: bool
) -> dict[str, Any] | None:
    candidate.update(attach_canonical_decision_metadata(candidate))
    candidate["live_block_reason"] = (
        "auto-buy is candidate discovery only; execution delegated to canonical signal path"
    )
    candidate["auto_buy_runtime_effect"] = "candidate_discovery_only_no_order_routing"
    candidate["live_requested"] = bool(live_requested)
    candidate["market_open"] = bool(market_open)
    return None


def route_paper_discovery_candidates() -> list[Any]:
    config = bridge_config_from_env(target_date=_today())
    bridge = DiscoveryExecutionBridgeService(
        db_path=DB_PATH,
        broker=get_default_broker_service(),
        config=config,
    )
    return bridge.route_eligible_candidates()


def symbols_for_scope(scope: str) -> list[str]:
    if scope == "all":
        return APPROVED_SYMBOLS_LIST
    if scope == "tradingview":
        return [
            s for s in APPROVED_SYMBOLS_LIST if SYMBOL_SIGNAL_SOURCE.get(s) == "tradingview_alert"
        ]
    return INTERNAL_BAR_ONLY_SYMBOLS_LIST


def window_symbols_for_run(
    symbols: list[str],
    *,
    max_symbols: int | None = None,
    rotation_bucket: int | None = None,
) -> tuple[list[str], int | None, int]:
    max_symbols = AUTO_BUY_MAX_SYMBOLS_PER_RUN if max_symbols is None else int(max_symbols)
    total_symbols = len(symbols)
    if max_symbols < 0:
        max_symbols = max(1, (total_symbols + 1) // 2)
    if max_symbols == 0 or total_symbols <= max_symbols:
        return list(symbols), None, total_symbols
    bucket = int(time.time() // 120) if rotation_bucket is None else int(rotation_bucket)
    start_idx = (bucket * max_symbols) % total_symbols
    rotated = symbols[start_idx:] + symbols[:start_idx]
    return rotated[:max_symbols], start_idx, total_symbols


def append_hard_block_audit_reason(candidate: dict[str, Any], reason: str) -> None:
    reasons = list(candidate.get("hard_block_audit_reasons") or [])
    if reason and reason not in reasons:
        reasons.append(reason)
    candidate["hard_block_audit_active"] = bool(reasons)
    candidate["hard_block_audit_reasons"] = reasons
    candidate["hard_block_audit_reason_count"] = len(reasons)
    candidate["hard_block_audit_reason"] = "; ".join(reasons) if reasons else None


def symbol_window_summary(scope: str, evaluated_count: int) -> dict[str, Any]:
    total_symbols = len(symbols_for_scope(scope))
    configured_cap = int(AUTO_BUY_MAX_SYMBOLS_PER_RUN)
    effective_cap = max(1, (total_symbols + 1) // 2) if configured_cap < 0 else configured_cap
    bounded = effective_cap > 0 and evaluated_count < total_symbols
    mode = (
        "half_universe"
        if configured_cap < 0
        else "full_universe"
        if configured_cap == 0
        else "fixed_cap"
    )
    return {
        "scope": scope,
        "evaluated": int(evaluated_count),
        "total": int(total_symbols),
        "max_symbols_per_run": configured_cap,
        "effective_symbol_cap": int(effective_cap),
        "mode": mode,
        "bounded": bool(bounded),
        "runtime_effect": (
            "rotating_symbol_window_to_keep_auto_buy_within_cron_cadence"
            if bounded
            else "full_symbol_universe_evaluated"
        ),
    }


AUTO_BUY_MAX_SIGNALS_PER_SYMBOL = int(os.getenv("AUTO_BUY_MAX_SIGNALS_PER_SYMBOL", "2"))
AUTO_BUY_MAX_SYMBOLS_PER_RUN = int(os.getenv("AUTO_BUY_MAX_SYMBOLS_PER_RUN", "20"))
AUTO_BUY_TIMING_LOG_ENABLED = os.getenv("AUTO_BUY_TIMING_LOG_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
AUTO_BUY_SCORE_DETAIL_LOG_ENABLED = os.getenv(
    "AUTO_BUY_SCORE_DETAIL_LOG_ENABLED", "true"
).lower() in (
    "1",
    "true",
    "yes",
    "on",
)

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
    started = time.monotonic()

    def _phase(label: str, phase_started: float) -> float:
        if AUTO_BUY_TIMING_LOG_ENABLED:
            elapsed = time.monotonic() - phase_started
            if elapsed >= 0.25:
                print(f"[TIMING] auto_buy.{label} elapsed={elapsed:.2f}s", flush=True)
        return time.monotonic()

    phase_started = time.monotonic()
    ctx = load_market_context()
    phase_started = _phase("load_market_context", phase_started)
    symbols_ctx = ctx.get("symbols") or {}
    rolling_context = load_rolling_momentum_context()
    phase_started = _phase("load_rolling_momentum_context", phase_started)
    intraday_feedback_evidence = (
        intraday_feedback_service().build_evidence(_today())
        if AUTO_BUY_INTRADAY_FEEDBACK_ENABLED
        else {}
    )
    phase_started = _phase("load_intraday_feedback_evidence", phase_started)
    held = held_symbols()
    phase_started = _phase("load_held_symbols", phase_started)
    candidates = []

    # Market-level session gate: if the broad market (QQQ/SPY) is fading or in
    # downtrend, cap all candidates at 'watch' regardless of individual scores.
    mkt_label, mkt_reason = market_session_label()
    market_suppressed = mkt_label in SUPPRESSED_LABELS

    symbols = symbols_for_scope(scope)
    symbols, start_idx, total_symbols = window_symbols_for_run(symbols)
    if start_idx is not None:
        if AUTO_BUY_TIMING_LOG_ENABLED:
            print(
                "[TIMING] auto_buy.symbol_window "
                f"scope={scope} start={start_idx} selected={len(symbols)} total={total_symbols}",
                flush=True,
            )
    phase_started = _phase("load_symbols_for_scope", phase_started)
    for symbol in symbols:
        symbol_started = time.monotonic()
        if AUTO_BUY_TIMING_LOG_ENABLED:
            print(f"[TIMING] auto_buy.evaluate_symbol_start symbol={symbol}", flush=True)
        session_started = time.monotonic()
        session = latest_session(symbol)
        if AUTO_BUY_TIMING_LOG_ENABLED:
            session_elapsed = time.monotonic() - session_started
            if session_elapsed >= 0.25:
                print(
                    f"[TIMING] auto_buy.latest_session symbol={symbol} "
                    f"elapsed={session_elapsed:.2f}s",
                    flush=True,
                )
        feature_started = time.monotonic()
        feature = latest_feature(symbol)
        if AUTO_BUY_TIMING_LOG_ENABLED:
            feature_elapsed = time.monotonic() - feature_started
            if feature_elapsed >= 0.25:
                print(
                    f"[TIMING] auto_buy.latest_feature symbol={symbol} "
                    f"elapsed={feature_elapsed:.2f}s",
                    flush=True,
                )
        evaluation_started = time.monotonic()
        candidate = evaluate_auto_buy_candidate(
            symbol=symbol,
            session=session,
            feature=feature,
            context=symbols_ctx.get(symbol) or {},
            rolling_context=rolling_context.get(symbol.upper()) or {},
            intraday_feedback_evidence=intraday_feedback_evidence,
            held=held,
            signal_source=SYMBOL_SIGNAL_SOURCE.get(symbol, "unknown"),
        )
        if AUTO_BUY_TIMING_LOG_ENABLED:
            evaluation_elapsed = time.monotonic() - evaluation_started
            if evaluation_elapsed >= 0.25:
                print(
                    f"[TIMING] auto_buy.evaluate_candidate symbol={symbol} "
                    f"elapsed={evaluation_elapsed:.2f}s",
                    flush=True,
                )

        # Downgrade strong_buy_candidate → watch when market session is suppressed.
        if market_suppressed and candidate.get("decision") == "strong_buy_candidate":
            block_reason = f"session_momentum_gate: {mkt_reason}={mkt_label}"
            candidate["decision"] = "watch"
            candidate["severity"] = "medium"
            candidate["hard_block_reason"] = (
                (candidate.get("hard_block_reason") or "") + f"; {block_reason}"
            ).lstrip("; ")
            append_hard_block_audit_reason(candidate, block_reason)

        # Per-symbol daily signal cap: if this symbol has already fired
        # strong_buy_candidate twice today without a filled order, suppress it.
        if candidate.get("decision") == "strong_buy_candidate":
            prior_signals = strong_buy_signals_today(symbol)
            if prior_signals >= AUTO_BUY_MAX_SIGNALS_PER_SYMBOL:
                block_reason = (
                    f"daily_signal_cap: {prior_signals}>={AUTO_BUY_MAX_SIGNALS_PER_SYMBOL} "
                    "unfilled signals today"
                )
                candidate["decision"] = "skip"
                candidate["severity"] = "low"
                candidate["hard_block_reason"] = (
                    (candidate.get("hard_block_reason") or "") + f"; {block_reason}"
                ).lstrip("; ")
                append_hard_block_audit_reason(candidate, block_reason)

        candidates.append(candidate)
        if AUTO_BUY_TIMING_LOG_ENABLED:
            symbol_elapsed = time.monotonic() - symbol_started
            if symbol_elapsed >= 1.0:
                print(
                    f"[TIMING] auto_buy.evaluate_symbol symbol={symbol} "
                    f"elapsed={symbol_elapsed:.2f}s decision={candidate.get('decision')}",
                    flush=True,
                )

    candidates.sort(key=lambda item: item.get("score") or 0, reverse=True)
    if AUTO_BUY_TIMING_LOG_ENABLED:
        print(
            f"[TIMING] auto_buy.build_candidates scope={scope} symbols={len(symbols)} "
            f"elapsed={time.monotonic() - started:.2f}s",
            flush=True,
        )
    return candidates


def _log_value(value: Any, default: str = "-") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _pct_text(value: Any) -> str:
    parsed = _to_float(value)
    return "-" if parsed is None else f"{parsed:.1f}%"


def _render_scoring_details(candidates: list[dict[str, Any]]) -> None:
    if not AUTO_BUY_SCORE_DETAIL_LOG_ENABLED:
        return

    conviction_cfg = load_conviction_config()
    print()
    print("  Scoring Breakdown")
    print(
        "  Conviction gate: "
        f"confluence_score >= {conviction_cfg.min_score:.1f}; "
        f"probability_gate_mode={conviction_cfg.probability_gate_mode}; "
        f"profit_probability >= {conviction_cfg.min_probability_pct:.1f}%; "
        f"system_probability >= {conviction_cfg.min_system_probability_pct:.1f}%; "
        f"profit_floor >= {conviction_cfg.min_probability_floor_pct:.1f}%; "
        f"system_floor >= {conviction_cfg.min_system_probability_floor_pct:.1f}%; "
        f"profit_percentile >= {conviction_cfg.min_probability_percentile_pct:.1f}%; "
        f"system_percentile >= {conviction_cfg.min_system_probability_percentile_pct:.1f}%; "
        f"min_dist_n={conviction_cfg.min_probability_distribution_size}; "
        f"require_probability={conviction_cfg.require_probability}; "
        f"max_positions={conviction_cfg.max_concurrent_positions}"
    )
    print("-" * 156)
    for c in candidates:
        print(
            f"  {c.get('symbol', '-'):<6} "
            f"final_score={_log_value(c.get('score'))} "
            f"confluence_score={_log_value(c.get('confluence_score'))} "
            f"conviction_score={_log_value(c.get('conviction_score'))} "
            f"auto_buy_threshold={_log_value(c.get('strong_buy_threshold'))} "
            f"decision={c.get('decision', '-')}"
        )
        print(
            "    probability: "
            f"selected={_pct_text(c.get('probability_pct'))} "
            f"source={_log_value(c.get('probability_source'))} "
            f"percentile={_pct_text(c.get('probability_percentile_pct'))} "
            f"dist_n={_log_value(c.get('probability_distribution_size'))} "
            f"prediction={_pct_text(c.get('prediction_probability_pct'))} "
            f"prediction_source={_log_value(c.get('prediction_probability_source'))} "
            f"prediction_percentile={_pct_text(c.get('prediction_probability_percentile_pct'))} "
            f"prediction_dist_n={_log_value(c.get('prediction_probability_distribution_size'))} "
            f"profit={_pct_text(c.get('prediction_probability_of_profit_pct'))} "
            f"approval={_pct_text(c.get('prediction_probability_of_approval_pct'))} "
            f"order={_pct_text(c.get('prediction_probability_of_order_pct'))}"
        )
        print(
            "    session: "
            f"label={_log_value(c.get('session_trend_label'))} "
            f"score={_log_value(c.get('session_trend_score'))} "
            f"return={_pct_text(c.get('session_return_pct'))} "
            f"m5={_pct_text(c.get('momentum_5m_pct'))} "
            f"m15={_pct_text(c.get('momentum_15m_pct'))} "
            f"m30={_pct_text(c.get('momentum_30m_pct'))} "
            f"m60={_pct_text(c.get('momentum_60m_pct'))} "
            f"m120={_pct_text(c.get('momentum_120m_pct'))} "
            f"vwap_dist={_pct_text(c.get('distance_from_vwap_pct'))}"
        )
        print(
            "    structure: "
            f"trend_regime={_log_value(c.get('trend_regime'))} "
            f"trend_persistence={_log_value(c.get('trend_persistence_score'))} "
            f"pullback_with_trend={_log_value(c.get('pullback_with_trend_score'))} "
            f"late_chase={_log_value(c.get('late_chase_maturity_score'))} "
            f"five_day={_pct_text(c.get('five_day_return_pct'))} "
            f"rolling_continuation={_log_value(c.get('rolling_continuation_score'))}"
        )
        print(
            "    setup_memory: "
            f"setup={_log_value(c.get('setup_recommendation'))}/"
            f"{_log_value(c.get('setup_label'))} "
            f"setup_score={_log_value(c.get('setup_score'))} "
            f"strategy_memory={_log_value(c.get('strategy_memory_recommendation'))} "
            f"learned_min_setup={_log_value(c.get('strategy_memory_min_setup_score'))} "
            f"memory_available={_log_value(c.get('strategy_memory_available'))}"
        )
        print(
            "    ml_layers: "
            f"evaluation_depth={_log_value(c.get('layered_ml_evaluation_depth'))} "
            f"available={_log_value(c.get('layered_ml_available'))} "
            f"instruction={_log_value(c.get('layered_ml_final_instruction'))} "
            f"ensemble_prob={_pct_text(c.get('layered_ml_ensemble_probability_pct'))} "
            f"master_confidence={_log_value(c.get('layered_ml_master_confidence_score'))} "
            f"promotion={_log_value(c.get('layered_ml_promotion_applied'))}"
        )
        print(
            "    feedback: "
            f"intraday_status={_log_value(c.get('intraday_feedback_status'))} "
            f"intraday_penalty={_log_value(c.get('intraday_feedback_score_penalty'))} "
            f"hard_block={_log_value(c.get('hard_block_reason'))}"
        )
        print(f"    score_reasons: {c.get('reason') or '-'}")


def render(candidates: list[dict[str, Any]], scope: str, market_open: bool) -> None:
    window = symbol_window_summary(scope, len(candidates))
    print("=" * 112)
    print("  Auto-Buy Candidate Manager")
    print("=" * 112)
    print(f"  scope          : {scope}")
    print(f"  symbols        : {window['evaluated']} of {window['total']}")
    print(f"  symbol_window  : {window['runtime_effect']}")
    print(f"  window_mode    : {window['mode']}")
    print(f"  window_cap     : {window['effective_symbol_cap']}")
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
    _render_scoring_details(candidates)


def main() -> int:
    if __name__ == "__main__":
        reexec_under_venv_if_available()

    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("internal", "tradingview", "all"), default="internal")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Record live-requested candidate metadata; auto-buy does not route orders",
    )
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
        candidate_started = time.monotonic()
        order = None
        if submitted < AUTO_BUY_MAX_ORDERS_PER_RUN:
            execution_started = time.monotonic()
            order = maybe_execute_auto_buy(
                candidate, market_open=market_open, live_requested=args.live
            )
            if AUTO_BUY_TIMING_LOG_ENABLED:
                execution_elapsed = time.monotonic() - execution_started
                if execution_elapsed >= 0.25:
                    print(
                        "[TIMING] auto_buy.post_build.maybe_execute "
                        f"symbol={candidate.get('symbol')} elapsed={execution_elapsed:.2f}s",
                        flush=True,
                    )
            if order:
                submitted += 1
        else:
            candidate["live_block_reason"] = (
                f"per-run auto-buy order cap reached: {submitted} >= {AUTO_BUY_MAX_ORDERS_PER_RUN}"
            )

        log_candidate_started = time.monotonic()
        log_candidate(candidate, live_buy_enabled=args.live and AUTO_BUY_LIVE_BUYS, order=order)
        if AUTO_BUY_TIMING_LOG_ENABLED:
            log_candidate_elapsed = time.monotonic() - log_candidate_started
            if log_candidate_elapsed >= 0.25:
                print(
                    "[TIMING] auto_buy.post_build.log_candidate "
                    f"symbol={candidate.get('symbol')} elapsed={log_candidate_elapsed:.2f}s",
                    flush=True,
                )
        log_event_started = time.monotonic()
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
        if AUTO_BUY_TIMING_LOG_ENABLED:
            log_event_elapsed = time.monotonic() - log_event_started
            if log_event_elapsed >= 0.25:
                print(
                    "[TIMING] auto_buy.post_build.log_event "
                    f"symbol={candidate.get('symbol')} elapsed={log_event_elapsed:.2f}s",
                    flush=True,
                )
            candidate_elapsed = time.monotonic() - candidate_started
            if candidate_elapsed >= 1.0:
                print(
                    "[TIMING] auto_buy.post_build.candidate "
                    f"symbol={candidate.get('symbol')} elapsed={candidate_elapsed:.2f}s",
                    flush=True,
                )

    bridge_results = []
    if args.live and AUTO_BUY_LIVE_BUYS and market_open and bridge_enabled_from_env():
        bridge_results = route_paper_discovery_candidates()

    if args.json:
        print(
            json.dumps(
                {
                    "candidates": candidates,
                    "symbol_window": symbol_window_summary(args.scope, len(candidates)),
                    "discovery_execution_bridge": bridge_results,
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
    else:
        render(candidates, args.scope, market_open)
        if bridge_results:
            print()
            print("  Discovery Execution Bridge")
            for result in bridge_results:
                print(
                    "  "
                    f"id={getattr(result, 'candidate_id', '-'):<6} "
                    f"symbol={getattr(result, 'symbol', '-'):<6} "
                    f"status={getattr(result, 'status', '-'):<8} "
                    f"order={getattr(result, 'routed_order_id', None) or '-'} "
                    f"reason={getattr(result, 'reason', None) or '-'}"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
