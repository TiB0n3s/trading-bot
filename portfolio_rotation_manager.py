#!/usr/bin/env python3
"""
Live portfolio rotation manager.

Reads portfolio_replacement_memory.json and, when explicitly enabled,
can sell the weakest holding to free a slot for a much stronger candidate.

Safety design:
- Does not buy.
- Does not override exposure, cooldown, churn, market hours, or circuit breaker.
- Only acts when recommendation is replace_now_candidate unless env says otherwise.
- Requires weakest holding to be sufficiently negative.
- Uses broker.py sell path so bracket cancellation and position validation stay centralized.
"""

import json
import os
from pathlib import Path
from datetime import datetime

import pytz

from bot_events import log_event
from db import DB_PATH, get_connection
from decision_snapshots import record_decision_snapshot
from intelligence_freshness import freshness_for_file
from services.broker_service import broker_service


BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "portfolio_replacement_memory.json"
ET = pytz.timezone("America/New_York")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return float(default)


LIVE_SELLS = env_bool("PORTFOLIO_REPLACEMENT_LIVE_SELLS", False)
MODE = os.getenv("PORTFOLIO_REPLACEMENT_MODE", "observe_only").strip().lower()
REQUIRE_REPLACE_NOW = env_bool("PORTFOLIO_REPLACEMENT_REQUIRE_REPLACE_NOW", True)
MIN_CANDIDATE_SCORE = env_float("PORTFOLIO_REPLACEMENT_MIN_CANDIDATE_SCORE", 120)
MIN_BUY_SCORE = env_float("PORTFOLIO_REPLACEMENT_MIN_BUY_SCORE", 15)
WEAK_HOLDING_PLPC = env_float("PORTFOLIO_REPLACEMENT_WEAK_HOLDING_PLPC", -1.00)


def load_memory():
    if not MEMORY_FILE.exists():
        return None, f"{MEMORY_FILE.name} not found"

    try:
        return json.loads(MEMORY_FILE.read_text()), None
    except Exception as e:
        return None, f"failed to parse {MEMORY_FILE.name}: {e}"


def evaluate_rotation(memory):
    weakest = memory.get("weakest_holding") or {}
    strongest = memory.get("strongest_candidate") or {}
    candidates = memory.get("replacement_candidates") or []

    recommendation = memory.get("recommendation")
    reason = memory.get("reason") or ""

    decision = {
        "action": "hold",
        "decision": "observe_only",
        "reason": "no live rotation trigger",
        "memory_recommendation": recommendation,
        "weakest": weakest,
        "strongest": strongest,
        "candidate": candidates[0] if candidates else None,
        "memory": memory,
    }

    replacement_freshness = freshness_for_file("portfolio_replacement")
    decision["replacement_freshness"] = replacement_freshness

    if MODE != "live_rotation":
        decision.update({
            "decision": "disabled",
            "reason": f"PORTFOLIO_REPLACEMENT_MODE={MODE}",
        })
        return decision

    if not replacement_freshness.get("fresh"):
        decision.update({
            "decision": "stale_replacement_memory",
            "reason": (
                "portfolio replacement memory is not fresh: "
                f"{replacement_freshness.get('status')} - {replacement_freshness.get('reason')}"
            ),
        })
        return decision

    if not LIVE_SELLS:
        decision.update({
            "decision": "live_sells_disabled",
            "reason": "PORTFOLIO_REPLACEMENT_LIVE_SELLS is false",
        })
        return decision

    if REQUIRE_REPLACE_NOW and recommendation != "replace_now_candidate":
        decision.update({
            "decision": "no_replace_now",
            "reason": f"recommendation={recommendation}; require replace_now_candidate",
        })
        return decision

    candidate = candidates[0] if candidates else strongest
    if not candidate:
        decision.update({
            "decision": "no_candidate",
            "reason": "no replacement candidate available",
        })
        return decision

    weakest_symbol = weakest.get("symbol")
    weakest_plpc = float(weakest.get("unrealized_plpc") or 0)
    candidate_symbol = candidate.get("symbol")
    candidate_score = float(candidate.get("score") or 0)
    buy_score = float(candidate.get("buy_opportunity_score") or 0)

    if not weakest_symbol:
        decision.update({
            "decision": "no_weakest_holding",
            "reason": "memory has no weakest_holding.symbol",
        })
        return decision

    if not candidate_symbol:
        decision.update({
            "decision": "no_candidate_symbol",
            "reason": "candidate has no symbol",
        })
        return decision

    if weakest_symbol == candidate_symbol:
        decision.update({
            "decision": "candidate_is_weakest",
            "reason": f"candidate and weakest are both {candidate_symbol}",
        })
        return decision

    if weakest_plpc > WEAK_HOLDING_PLPC:
        decision.update({
            "decision": "weakest_not_weak_enough",
            "reason": f"{weakest_symbol} plpc={weakest_plpc:.2f}% > threshold {WEAK_HOLDING_PLPC:.2f}%",
        })
        return decision

    if candidate_score < MIN_CANDIDATE_SCORE:
        decision.update({
            "decision": "candidate_score_too_low",
            "reason": f"{candidate_symbol} score={candidate_score:.2f} < {MIN_CANDIDATE_SCORE:.2f}",
        })
        return decision

    if buy_score < MIN_BUY_SCORE:
        decision.update({
            "decision": "buy_score_too_low",
            "reason": f"{candidate_symbol} buy_score={buy_score:.2f} < {MIN_BUY_SCORE:.2f}",
        })
        return decision

    decision.update({
        "action": "sell_weakest",
        "decision": "replace_now_live",
        "symbol_to_sell": weakest_symbol,
        "candidate_symbol": candidate_symbol,
        "reason": (
            f"live rotation: sell weakest {weakest_symbol} plpc={weakest_plpc:.2f}% "
            f"to free slot for {candidate_symbol}; candidate_score={candidate_score:.2f}; "
            f"buy_score={buy_score:.2f}; memory_reason={reason}"
        ),
    })
    return decision


def _now_et_string() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")


def log_rotation_sell(decision: dict, order: dict | None) -> int | None:
    """Write live portfolio-rotation sells into trades.db for fill tracking."""
    if not order:
        return None

    order_id = order.get("order_id") if isinstance(order, dict) else None
    if not order_id:
        return None

    with get_connection(DB_PATH) as con:
        existing = con.execute(
            "SELECT id FROM trades WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
        if existing:
            return int(existing["id"])

        cur = con.execute(
            """
            INSERT INTO trades (
                timestamp,
                symbol,
                action,
                signal_price,
                approved,
                rejection_reason,
                confidence,
                position_size_pct,
                stop_loss_pct,
                take_profit_pct,
                order_id,
                order_status,
                qty,
                fill_price
            ) VALUES (?, ?, 'sell', ?, 1, ?, ?, 0.0, 0.0, 0.0, ?, ?, ?, NULL)
            """,
            (
                _now_et_string(),
                decision.get("symbol_to_sell"),
                order.get("current_price"),
                "portfolio_rotation_manager: live replacement sell submitted; "
                + str(decision.get("reason") or ""),
                "portfolio_rotation_manager",
                order_id,
                order.get("status") or "submitted",
                int(float(order.get("qty"))) if order.get("qty") is not None else None,
            ),
        )
        return int(cur.lastrowid)


def record_rotation_snapshot(decision: dict, order: dict | None, trade_id: int | None) -> None:
    """Record an immutable audit row for every portfolio-rotation decision."""
    weakest = decision.get("weakest") or {}
    candidate = decision.get("candidate") or decision.get("strongest") or {}
    timestamp = _now_et_string()

    snapshot_decision = {
        "approved": decision.get("decision") == "replace_now_live" and bool(order),
        "decision": decision.get("decision"),
        "confidence": "portfolio_rotation_manager",
        "position_size_pct": 0.0,
        "stop_loss_pct": 0.0,
        "take_profit_pct": 0.0,
        "reason": decision.get("reason"),
    }
    context = {
        "market_bias": (candidate or {}).get("market_bias"),
        "risk_level": (candidate or {}).get("risk_level"),
        "entry_quality": (candidate or {}).get("entry_quality"),
        "session_trend_label": (candidate or {}).get("session_trend_label"),
        "session_trend_score": (candidate or {}).get("session_trend_score"),
    }
    account_state = {
        "portfolio_rotation": {
            "mode": MODE,
            "live_sells": LIVE_SELLS,
            "decision": decision,
            "runtime_effect": "sell_only_live_rotation" if order else "observe_or_block",
        }
    }

    record_decision_snapshot(
        trade_id=trade_id,
        timestamp=timestamp,
        source="portfolio_rotation_manager.py",
        symbol=decision.get("symbol_to_sell") or weakest.get("symbol"),
        action="sell",
        signal_price=weakest.get("current_price") or weakest.get("market_value"),
        decision=snapshot_decision,
        order=order or {},
        context=context,
        account_state=account_state,
        raw_signal={"portfolio_replacement_memory": decision.get("memory")},
        rejection_reason=None if snapshot_decision["approved"] else decision.get("reason"),
    )


def main():
    memory, err = load_memory()
    if err:
        print(f"Portfolio rotation manager: {err}")
        log_event(
            event_type="PORTFOLIO_ROTATION",
            decision="memory_unavailable",
            severity="warning",
            reason=err,
            source="portfolio_rotation_manager.py",
        )
        return

    decision = evaluate_rotation(memory)

    print("=" * 96)
    print("  Portfolio Rotation Manager")
    print("=" * 96)
    print(f"mode={MODE} live_sells={LIVE_SELLS}")
    print(f"decision={decision.get('decision')}")
    print(f"reason={decision.get('reason')}")

    log_event(
        event_type="PORTFOLIO_ROTATION",
        symbol=decision.get("symbol_to_sell") or (decision.get("weakest") or {}).get("symbol"),
        action=decision.get("action"),
        decision=decision.get("decision"),
        severity="high" if decision.get("decision") == "replace_now_live" else "info",
        reason=decision.get("reason"),
        source="portfolio_rotation_manager.py",
        payload=decision,
    )

    if decision.get("decision") != "replace_now_live":
        record_rotation_snapshot(decision, None, None)
        return

    symbol = decision.get("symbol_to_sell")
    print(f"Submitting live sell for weakest holding: {symbol}")

    result = broker_service.place_order(symbol, "sell", 0, 0, 0)
    print(f"sell_result={result}")
    trade_id = log_rotation_sell(decision, result)
    record_rotation_snapshot(decision, result, trade_id)

    log_event(
        event_type="PORTFOLIO_ROTATION_ORDER",
        symbol=symbol,
        action="sell",
        decision="submitted" if result else "failed",
        severity="high",
        reason=decision.get("reason"),
        source="portfolio_rotation_manager.py",
        payload={"decision": decision, "order": result},
    )


if __name__ == "__main__":
    main()
