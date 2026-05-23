#!/usr/bin/env python3
"""
Replay engine helpers.

Read-only strategy replay utilities.

This is the foundation for testing new scoring/risk logic against historical
signals before promoting it into live decision flow.
"""

from __future__ import annotations

from typing import Any
from strategy.setup_classifier import classify_setup
from db import DB_PATH, get_connection
from strategy.trade_scorer import score_trade


def fetch_trade_rows(
    date_prefix: str | None = None,
    limit: int | None = None,
    db_path=DB_PATH,
) -> list[dict[str, Any]]:
    """Fetch trades rows for replay."""
    where = "WHERE 1=1"
    params: list[Any] = []

    if date_prefix:
        where += " AND timestamp LIKE ?"
        params.append(f"{date_prefix}%")

    limit_sql = ""
    if limit:
        limit_sql = " LIMIT ?"
        params.append(int(limit))

    with get_connection(db_path) as con:
        rows = con.execute(
            f"""
            SELECT *
            FROM trades
            {where}
            ORDER BY id ASC
            {limit_sql}
            """,
            params,
        ).fetchall()

    return [dict(r) for r in rows]


def trend_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "direction": row.get("trend_direction"),
        "strength": row.get("trend_strength"),
        "consecutive_count": row.get("trend_consecutive_count") or 0,
    }


def momentum_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "direction": row.get("momentum_direction"),
        "momentum_pct": row.get("momentum_pct"),
        "premarket_alignment": row.get("premarket_alignment"),
    }


def alignment_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "benchmark": row.get("benchmark"),
        "aligned_for_buy": row.get("benchmark_aligned"),
    }


def account_state_from_row(row: dict[str, Any]) -> dict[str, Any]:
    state = {}

    if row.get("macro_regime") is not None or row.get("risk_multiplier") is not None:
        state["macro_risk"] = {
            "macro_regime": row.get("macro_regime"),
            "risk_multiplier": row.get("risk_multiplier"),
        }

    if row.get("market_bias") is not None:
        state["market_bias"] = row.get("market_bias")

    if row.get("fundamental_score") is not None:
        state["fundamental_score"] = row.get("fundamental_score")

    if row.get("risk_level") is not None:
        state["risk_level"] = row.get("risk_level")

    if row.get("entry_quality") is not None:
        state["entry_quality"] = row.get("entry_quality")

    return state


def replay_row(row: dict[str, Any]) -> dict[str, Any]:
    """Replay one trades row through the current trader-brain scorer."""
    symbol = row.get("symbol")
    action = row.get("action")

    if not symbol or action not in ("buy", "sell"):
        return {
            "id": row.get("id"),
            "symbol": symbol,
            "action": action,
            "replayable": False,
            "reason": "missing symbol or unsupported action",
        }

    thesis = score_trade(
        symbol=symbol,
        action=action,
        account_state=account_state_from_row(row),
        trend=trend_from_row(row),
        momentum=momentum_from_row(row),
        market_alignment=alignment_from_row(row),
        tape=row.get("tape") or {},
    )

    setup_classification = classify_setup(
        thesis.to_dict(),
        tape=row.get("tape") or {},
    )

    original_approved = bool(row.get("approved"))
    replay_approved = bool(thesis.approved_by_scorer)

    return {
        "id": row.get("id"),
        "timestamp": row.get("timestamp"),
        "symbol": symbol,
        "action": action,
        "original_approved": original_approved,
        "replay_approved": replay_approved,
        "agreement": original_approved == replay_approved,
        "score": thesis.score,
        "setup_classification": setup_classification,
        "setup_label": setup_classification.get("label"),
        "setup_posture": setup_classification.get("posture"),
        "setup_type": thesis.setup_type,
        "reason": thesis.reason,
        "replayable": True,
    }


def replay_trades(
    date_prefix: str | None = None,
    limit: int | None = None,
    db_path=DB_PATH,
) -> list[dict[str, Any]]:
    rows = fetch_trade_rows(date_prefix=date_prefix, limit=limit, db_path=db_path)
    return [replay_row(row) for row in rows]


def replay_summary(
    date_prefix: str | None = None,
    limit: int | None = None,
    db_path=DB_PATH,
) -> dict[str, Any]:
    results = replay_trades(date_prefix=date_prefix, limit=limit, db_path=db_path)
    replayable = [r for r in results if r.get("replayable")]

    agree = sum(1 for r in replayable if r.get("agreement"))
    disagree = len(replayable) - agree

    bot_yes_brain_no = sum(
        1 for r in replayable
        if r.get("original_approved") and not r.get("replay_approved")
    )
    bot_no_brain_yes = sum(
        1 for r in replayable
        if not r.get("original_approved") and r.get("replay_approved")
    )

    avg_score = (
        sum(float(r.get("score") or 0) for r in replayable) / len(replayable)
        if replayable else 0.0
    )

    return {
        "date_prefix": date_prefix,
        "total_rows": len(results),
        "replayable_rows": len(replayable),
        "agreement": agree,
        "disagreement": disagree,
        "bot_approved_brain_rejected": bot_yes_brain_no,
        "bot_rejected_brain_approved": bot_no_brain_yes,
        "avg_score": round(avg_score, 2),
        "results": results,
    }
