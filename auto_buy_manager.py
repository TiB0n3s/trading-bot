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
from risk.exposure import any_cluster_limit_hit, cluster_exposure
from services.candidate_universe_service import CandidateUniverseService
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
AUTO_BUY_MIN_SCORE = float(os.getenv("AUTO_BUY_MIN_SCORE", "13"))
AUTO_BUY_WATCH_SCORE = float(os.getenv("AUTO_BUY_WATCH_SCORE", "7"))
AUTO_BUY_POSITION_SIZE_PCT = float(os.getenv("AUTO_BUY_POSITION_SIZE_PCT", "0.50"))
AUTO_BUY_STOP_LOSS_PCT = float(os.getenv("AUTO_BUY_STOP_LOSS_PCT", "1.00"))
AUTO_BUY_TAKE_PROFIT_PCT = float(os.getenv("AUTO_BUY_TAKE_PROFIT_PCT", "2.00"))
AUTO_BUY_MAX_ORDERS_PER_RUN = int(os.getenv("AUTO_BUY_MAX_ORDERS_PER_RUN", "1"))
AUTO_BUY_MAX_DAILY_ORDERS = int(os.getenv("AUTO_BUY_MAX_DAILY_ORDERS", "3"))
AUTO_BUY_COOLDOWN_MINUTES = int(os.getenv("AUTO_BUY_COOLDOWN_MINUTES", "60"))
AUTO_BUY_SESSION_BUFFER_MINUTES = int(os.getenv("AUTO_BUY_SESSION_BUFFER_MINUTES", "10"))
APP_BUY_COOLDOWN_MINUTES = int(os.getenv("ORDER_COOLDOWN_MINUTES", "15"))
APP_RECENT_SELL_COOLDOWN_MINUTES = int(os.getenv("RECENT_SELL_COOLDOWN_MINUTES", "30"))
CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY = int(os.getenv("CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY", "1"))


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _today() -> str:
    return now_et().strftime("%Y-%m-%d")


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
    if app_approved_buys_today(symbol) >= CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY:
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
        }

    score = 0.0
    reasons = []

    bias = context.get("bias")
    entry_quality = context.get("entry_quality")
    risk_level = context.get("risk_level")
    avoid_type = context.get("avoid_type")

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
    elif vwap > 1.75:
        score -= 2
        reasons.append("extended_vwap:-2")
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

    if setup_score >= 70:
        score += 2
        reasons.append("setup_score>=70:+2")
    elif setup_score <= 20:
        score -= 2
        reasons.append("setup_score<=20:-2")

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
    hard_block_reason = "; ".join(hard_block_reasons) if hard_block_reasons else None

    strong_threshold = AUTO_BUY_MIN_SCORE
    if signal_source == "tradingview_alert" and not AUTO_BUY_ALLOW_TRADINGVIEW_LIVE:
        strong_threshold = AUTO_BUY_MIN_SCORE + 4.0
        reasons.append(f"webhook_symbol_candidate_threshold:{strong_threshold:.1f}")

    if hard_block_reasons:
        decision = "skip"
        severity = "blocked"
    elif score >= strong_threshold:
        decision = "strong_buy_candidate"
        severity = "high"
    elif score >= AUTO_BUY_WATCH_SCORE:
        decision = "watch"
        severity = "medium"
    else:
        decision = "skip"
        severity = "low"

    return {
        "symbol": symbol,
        "signal_source": signal_source,
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
        "momentum_5m_pct": m5,
        "momentum_15m_pct": m15,
        "momentum_30m_pct": m30,
        "distance_from_vwap_pct": vwap,
        "setup_label": setup_label,
        "setup_recommendation": setup_rec,
        "setup_score": setup_score,
        "feature_snapshot_id": feature.get("id"),
    }


def log_candidate(candidate: dict[str, Any], live_buy_enabled: bool, order: dict[str, Any] | None = None) -> None:
    order = order or {}
    timestamp = now_et().isoformat()
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
        and not AUTO_BUY_ALLOW_TRADINGVIEW_LIVE
    ):
        candidate["live_block_reason"] = (
            "tradingview alert symbol requires webhook approval path"
        )
        return None

    daily_orders = auto_buy_orders_today()
    if daily_orders >= AUTO_BUY_MAX_DAILY_ORDERS:
        candidate["live_block_reason"] = (
            f"daily auto-buy order cap reached: {daily_orders} >= {AUTO_BUY_MAX_DAILY_ORDERS}"
        )
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
        candidate["live_block_reason"] = "broker returned no order"
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
    print(f"  min_score      : {AUTO_BUY_MIN_SCORE}")
    print(f"  daily_cap      : {AUTO_BUY_MAX_DAILY_ORDERS}")
    print(f"  cooldown_min   : {AUTO_BUY_COOLDOWN_MINUTES}")
    print()
    print(
        f"{'Sym':<6} {'Source':<18} {'Decision':<22} {'Score':>6} "
        f"{'Session':<20} {'Setup':<34} Reason"
    )
    print("-" * 132)
    for c in candidates:
        print(
            f"{c['symbol']:<6} {c.get('signal_source', '-'):<18} "
            f"{c['decision']:<22} {c['score']:>6.1f} "
            f"{str(c.get('session_trend_label')) + '/' + str(c.get('session_trend_score')):<20} "
            f"{str(c.get('setup_label') or '-'):<34} "
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
