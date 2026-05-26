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
from datetime import datetime
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
from db import get_connection
from market_time import is_market_hours, now_et
from symbols_config import (
    APPROVED_SYMBOLS_LIST,
    INTERNAL_BAR_ONLY_SYMBOLS_LIST,
    SYMBOL_SIGNAL_SOURCE,
)


AUTO_BUY_LIVE_BUYS = os.getenv("AUTO_BUY_LIVE_BUYS", "false").lower() in ("1", "true", "yes", "on")
AUTO_BUY_MIN_SCORE = float(os.getenv("AUTO_BUY_MIN_SCORE", "13"))
AUTO_BUY_WATCH_SCORE = float(os.getenv("AUTO_BUY_WATCH_SCORE", "7"))
AUTO_BUY_POSITION_SIZE_PCT = float(os.getenv("AUTO_BUY_POSITION_SIZE_PCT", "0.50"))
AUTO_BUY_STOP_LOSS_PCT = float(os.getenv("AUTO_BUY_STOP_LOSS_PCT", "1.00"))
AUTO_BUY_TAKE_PROFIT_PCT = float(os.getenv("AUTO_BUY_TAKE_PROFIT_PCT", "2.00"))
AUTO_BUY_MAX_ORDERS_PER_RUN = int(os.getenv("AUTO_BUY_MAX_ORDERS_PER_RUN", "1"))
AUTO_BUY_MAX_DAILY_ORDERS = int(os.getenv("AUTO_BUY_MAX_DAILY_ORDERS", "3"))
AUTO_BUY_COOLDOWN_MINUTES = int(os.getenv("AUTO_BUY_COOLDOWN_MINUTES", "60"))


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _today() -> str:
    return now_et().strftime("%Y-%m-%d")


def init_auto_buy_table() -> None:
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_buy_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_source TEXT,
                decision TEXT,
                score REAL,
                reason TEXT,
                market_bias TEXT,
                entry_quality TEXT,
                risk_level TEXT,
                session_trend_label TEXT,
                session_trend_score REAL,
                session_return_pct REAL,
                momentum_5m_pct REAL,
                momentum_15m_pct REAL,
                momentum_30m_pct REAL,
                distance_from_vwap_pct REAL,
                setup_label TEXT,
                setup_recommendation TEXT,
                setup_score REAL,
                feature_snapshot_id INTEGER,
                live_buy_enabled INTEGER DEFAULT 0,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_candidates_timestamp
            ON auto_buy_candidates(timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_candidates_symbol
            ON auto_buy_candidates(symbol, timestamp)
            """
        )


def latest_session(symbol: str) -> dict[str, Any]:
    with get_connection(DB_PATH) as con:
        row = con.execute(
            "SELECT * FROM session_momentum WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    return dict(row) if row else {}


def latest_feature(symbol: str) -> dict[str, Any]:
    with get_connection(DB_PATH) as con:
        row = con.execute(
            """
            SELECT *
            FROM feature_snapshots
            WHERE symbol = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
    return dict(row) if row else {}


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
        from broker import api

        return {p.symbol.upper() for p in api.list_positions()}
    except Exception:
        return set()


def client_order_id(symbol: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"autobuy-{symbol.lower()}-{ts}"


def auto_buy_orders_today() -> int:
    with get_connection(DB_PATH) as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
              AND order_submitted = 1
            """,
            (_today(),),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def recently_auto_bought(symbol: str, cooldown_minutes: int = AUTO_BUY_COOLDOWN_MINUTES) -> tuple[bool, str]:
    with get_connection(DB_PATH) as con:
        row = con.execute(
            """
            SELECT timestamp, order_id
            FROM auto_buy_candidates
            WHERE symbol = ?
              AND order_submitted = 1
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()

    if not row:
        return False, "no recent auto-buy order"

    try:
        raw_ts = row["timestamp"]
        ts = datetime.fromisoformat(raw_ts)
        if ts.tzinfo is not None:
            ts = ts.astimezone(now_et().tzinfo).replace(tzinfo=None)
    except Exception:
        return True, "recent auto-buy timestamp could not be parsed"

    age_minutes = (now_et().replace(tzinfo=None) - ts).total_seconds() / 60.0
    if age_minutes < cooldown_minutes:
        return True, (
            f"last auto-buy order {age_minutes:.1f}m ago "
            f"< cooldown={cooldown_minutes}m order_id={row['order_id'] or '-'}"
        )

    return False, f"last auto-buy order {age_minutes:.1f}m ago"


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

    hard_block = (
        bias == "avoid"
        or setup_rec == "avoid"
        or label in ("downtrend", "fading")
        or m15 < -0.20
        or m30 < -0.35
    )

    if hard_block:
        decision = "skip"
        severity = "blocked"
    elif score >= AUTO_BUY_MIN_SCORE:
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
        "reason": "; ".join(reasons) if reasons else "no positive auto-buy evidence",
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
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO auto_buy_candidates (
                timestamp, symbol, signal_source, decision, score, reason,
                market_bias, entry_quality, risk_level,
                session_trend_label, session_trend_score, session_return_pct,
                momentum_5m_pct, momentum_15m_pct, momentum_30m_pct,
                distance_from_vwap_pct,
                setup_label, setup_recommendation, setup_score,
                feature_snapshot_id, live_buy_enabled, order_submitted, order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_et().isoformat(),
                candidate.get("symbol"),
                candidate.get("signal_source"),
                candidate.get("decision"),
                candidate.get("score"),
                candidate.get("reason"),
                candidate.get("market_bias"),
                candidate.get("entry_quality"),
                candidate.get("risk_level"),
                candidate.get("session_trend_label"),
                candidate.get("session_trend_score"),
                candidate.get("session_return_pct"),
                candidate.get("momentum_5m_pct"),
                candidate.get("momentum_15m_pct"),
                candidate.get("momentum_30m_pct"),
                candidate.get("distance_from_vwap_pct"),
                candidate.get("setup_label"),
                candidate.get("setup_recommendation"),
                candidate.get("setup_score"),
                candidate.get("feature_snapshot_id"),
                1 if live_buy_enabled else 0,
                1 if order else 0,
                order.get("order_id") if isinstance(order, dict) else None,
            ),
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

    from broker import place_order

    order = place_order(
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
    return order


def symbols_for_scope(scope: str) -> list[str]:
    if scope == "all":
        return APPROVED_SYMBOLS_LIST
    if scope == "tradingview":
        return [s for s in APPROVED_SYMBOLS_LIST if SYMBOL_SIGNAL_SOURCE.get(s) == "tradingview_alert"]
    return INTERNAL_BAR_ONLY_SYMBOLS_LIST


def build_candidates(scope: str) -> list[dict[str, Any]]:
    ctx = load_market_context()
    symbols_ctx = ctx.get("symbols") or {}
    held = held_symbols()
    candidates = []

    for symbol in symbols_for_scope(scope):
        candidate = evaluate_auto_buy_candidate(
            symbol=symbol,
            session=latest_session(symbol),
            feature=latest_feature(symbol),
            context=symbols_ctx.get(symbol) or {},
            held=held,
            signal_source=SYMBOL_SIGNAL_SOURCE.get(symbol, "unknown"),
        )
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
            f"{c.get('reason')}"
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
    market_open = is_market_hours(now_et())
    candidates = build_candidates(args.scope)

    submitted = 0
    for candidate in candidates:
        order = None
        if submitted < AUTO_BUY_MAX_ORDERS_PER_RUN:
            order = maybe_execute_auto_buy(candidate, market_open=market_open, live_requested=args.live)
            if order:
                submitted += 1

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
