#!/usr/bin/env python3
"""
Experience-based prediction model.

Observe-only:
- Reads daily_symbol_context, daily_symbol_events, trades, matched_trades.
- Writes daily_symbol_predictions.
- Does not place orders or alter live trading decisions.

Core idea:
For today's symbol context, find historically similar symbol/day rows and use
their outcomes to estimate probability of profit and expected P&L.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from statistics import mean

from db import DB_PATH, get_connection
from market_intelligence.intelligence_store import init_intelligence_tables


PREDICTION_COLUMNS = [
    "market_date",
    "symbol",
    "prediction_score",
    "probability_of_profit",
    "probability_of_approval",
    "probability_of_order",
    "expected_pnl",
    "expected_win_rate",
    "confidence",
    "sample_size",
    "similarity_basis",
    "reason",
    "raw_json",
    "created_at",
    "updated_at",
]


def init_prediction_tables(db_path: Path | str = DB_PATH) -> None:
    init_intelligence_tables(db_path)

    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_symbol_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                market_date TEXT NOT NULL,
                symbol TEXT NOT NULL,

                prediction_score REAL,
                probability_of_profit REAL,
                probability_of_approval REAL,
                probability_of_order REAL,
                expected_pnl REAL,
                expected_win_rate REAL,

                confidence TEXT,
                sample_size INTEGER,
                similarity_basis TEXT,
                reason TEXT,

                raw_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                UNIQUE(market_date, symbol)
            )
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_daily_symbol_predictions_date_symbol
            ON daily_symbol_predictions(market_date, symbol)
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_daily_symbol_predictions_symbol_date
            ON daily_symbol_predictions(symbol, market_date)
            """
        )


def score_bucket(value, label):
    if value is None:
        return f"{label}:missing"
    try:
        v = float(value)
    except Exception:
        return f"{label}:invalid"

    if v >= 80:
        return f"{label}:80-100"
    if v >= 60:
        return f"{label}:60-79"
    if v >= 40:
        return f"{label}:40-59"
    if v >= 20:
        return f"{label}:20-39"
    return f"{label}:0-19"


def pct_bucket(value, label):
    if value is None:
        return f"{label}:missing"
    try:
        v = float(value)
    except Exception:
        return f"{label}:invalid"

    if v >= 2:
        return f"{label}:+2%+"
    if v >= 0.5:
        return f"{label}:+0.5_to_2%"
    if v > -0.5:
        return f"{label}:-0.5_to_+0.5%"
    if v > -2:
        return f"{label}:-2_to_-0.5%"
    return f"{label}:-2%-"


def confidence_from_sample(sample_size: int) -> str:
    if sample_size >= 30:
        return "high"
    if sample_size >= 15:
        return "medium"
    if sample_size >= 5:
        return "low"
    return "very_low"


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v)))


def load_target_context(con, market_date: str, symbol: str):
    return con.execute(
        """
        SELECT *
        FROM daily_symbol_context
        WHERE market_date = ?
          AND symbol = ?
        """,
        (market_date, symbol),
    ).fetchone()


def load_target_events(con, market_date: str, symbol: str):
    return con.execute(
        """
        SELECT *
        FROM daily_symbol_events
        WHERE market_date = ?
          AND symbol = ?
        ORDER BY id
        """,
        (market_date, symbol),
    ).fetchall()


def load_historical_contexts(con, market_date: str, symbol: str | None = None):
    params = [market_date]
    symbol_filter = ""

    # Use all symbols by default so early model has more samples.
    # Symbol-specific similarity is rewarded separately.
    if symbol:
        symbol_filter = "AND symbol = ?"
        params.append(symbol)

    return con.execute(
        f"""
        SELECT *
        FROM daily_symbol_context
        WHERE market_date < ?
          {symbol_filter}
        ORDER BY market_date DESC, symbol
        """,
        params,
    ).fetchall()


def events_for_context(con, market_date: str, symbol: str):
    return con.execute(
        """
        SELECT event_type, expected_market_impact, trade_relevance,
               consumer_appetite_score, profit_potential_score,
               supply_chain_risk_score, competitive_risk_score
        FROM daily_symbol_events
        WHERE market_date = ?
          AND symbol = ?
        """,
        (market_date, symbol),
    ).fetchall()


def outcome_for_context(con, market_date: str, symbol: str):
    """Return trade/outcome stats for a symbol/date."""
    trades = con.execute(
        """
        SELECT *
        FROM trades
        WHERE timestamp LIKE ?
          AND symbol = ?
        """,
        (f"{market_date}%", symbol),
    ).fetchall()

    signals = len(trades)
    approved = sum(1 for r in trades if int(r["approved"] or 0) == 1)
    orders = sum(1 for r in trades if r["order_id"])
    filled = sum(
        1 for r in trades
        if r["order_status"] in ("filled", "partially_filled")
        and r["fill_price"] is not None
    )

    try:
        matched = con.execute(
            """
            SELECT *
            FROM matched_trades
            WHERE exit_timestamp LIKE ?
              AND symbol = ?
            """,
            (f"{market_date}%", symbol),
        ).fetchall()
    except Exception:
        matched = []

    closed = len(matched)
    pnl = sum(float(r["realized_pnl"] or 0) for r in matched)
    wins = sum(1 for r in matched if float(r["realized_pnl"] or 0) > 0)

    return {
        "signals": signals,
        "approved": approved,
        "orders": orders,
        "filled": filled,
        "closed_trades": closed,
        "realized_pnl": pnl,
        "wins": wins,
        "profitable": 1 if pnl > 0 else 0 if closed > 0 else None,
        "win_rate": wins / closed if closed else None,
        "expectancy": pnl / closed if closed else None,
    }


def event_signature(events):
    """Condense a list of event rows into simple comparable sets."""
    return {
        "event_types": {e["event_type"] for e in events if e["event_type"]},
        "impacts": {e["expected_market_impact"] for e in events if e["expected_market_impact"]},
        "relevance": {e["trade_relevance"] for e in events if e["trade_relevance"]},
    }


def similarity_score(target_ctx, target_events, hist_ctx, hist_events):
    """Weighted similarity score, 0-100-ish."""
    score = 0
    reasons = []

    target_sig = event_signature(target_events)
    hist_sig = event_signature(hist_events)

    if target_ctx["symbol"] == hist_ctx["symbol"]:
        score += 15
        reasons.append("same_symbol")

    for field, weight in (
        ("macro_regime", 8),
        ("bias", 10),
        ("risk_level", 10),
        ("entry_quality", 10),
        ("avoid_type", 5),
        ("sector_alignment", 5),
        ("index_alignment", 5),
        ("price_location", 4),
        ("volume_context", 4),
    ):
        if target_ctx[field] is not None and target_ctx[field] == hist_ctx[field]:
            score += weight
            reasons.append(field)

    for field, label, weight in (
        ("catalyst_score", "cat", 6),
        ("relative_strength_score", "rs", 5),
        ("consumer_appetite_score", "demand", 5),
        ("profit_potential_score", "profit", 5),
        ("supply_chain_risk_score", "supply", 5),
        ("competitive_risk_score", "comp", 4),
    ):
        if score_bucket(target_ctx[field], label) == score_bucket(hist_ctx[field], label):
            score += weight
            reasons.append(f"{label}_bucket")

    for field, label, weight in (
        ("daily_pct", "daily", 4),
        ("intraday_pct", "intra", 4),
        ("momentum_30m_pct", "mom30", 4),
    ):
        if pct_bucket(target_ctx[field], label) == pct_bucket(hist_ctx[field], label):
            score += weight
            reasons.append(f"{label}_bucket")

    if target_sig["event_types"] and target_sig["event_types"] & hist_sig["event_types"]:
        score += 15
        reasons.append("event_type_overlap")

    if target_sig["impacts"] and target_sig["impacts"] & hist_sig["impacts"]:
        score += 10
        reasons.append("impact_overlap")

    if target_sig["relevance"] and target_sig["relevance"] & hist_sig["relevance"]:
        score += 10
        reasons.append("relevance_overlap")

    return score, reasons


def prediction_from_matches(target_ctx, matches):
    """Create probability/score from weighted historical matches."""
    if not matches:
        return {
            "prediction_score": 50.0,
            "probability_of_profit": None,
            "probability_of_approval": None,
            "probability_of_order": None,
            "expected_pnl": None,
            "expected_win_rate": None,
            "confidence": "very_low",
            "sample_size": 0,
            "similarity_basis": "no historical matches",
            "reason": "No historical context rows available yet; neutral observe-only prediction.",
            "raw": {
                "matches": [],
            },
        }

    # Use top 30 matches. Require score > 0, but early history may be sparse.
    matches = sorted(matches, key=lambda m: m["similarity_score"], reverse=True)
    top = matches[:30]

    outcomes = [m["outcome"] for m in top]
    with_signals = [o for o in outcomes if o["signals"] > 0]
    with_closed = [o for o in outcomes if o["closed_trades"] > 0]

    probability_of_approval = (
        sum(o["approved"] for o in with_signals) / sum(o["signals"] for o in with_signals)
        if with_signals and sum(o["signals"] for o in with_signals) > 0
        else None
    )

    probability_of_order = (
        sum(o["orders"] for o in with_signals) / sum(o["signals"] for o in with_signals)
        if with_signals and sum(o["signals"] for o in with_signals) > 0
        else None
    )

    if with_closed:
        profitable = sum(1 for o in with_closed if o["realized_pnl"] > 0)
        probability_of_profit = profitable / len(with_closed)
        expected_pnl = mean(o["expectancy"] for o in with_closed if o["expectancy"] is not None)
        expected_win_rate = mean(o["win_rate"] for o in with_closed if o["win_rate"] is not None)
    else:
        probability_of_profit = None
        expected_pnl = None
        expected_win_rate = None

    # Score starts neutral. It only becomes strong with real closed-trade evidence.
    prediction_score = 50.0

    if probability_of_profit is not None:
        prediction_score += (probability_of_profit - 0.5) * 50

    if expected_pnl is not None:
        # Scale gently; $5 avg expectancy is a meaningful positive signal in this paper setup.
        prediction_score += max(-15, min(15, expected_pnl * 3))

    # Add small context-based modifiers, not enough to overpower history.
    if target_ctx["catalyst_score"] is not None:
        prediction_score += (float(target_ctx["catalyst_score"]) - 50) * 0.08

    if target_ctx["supply_chain_risk_score"] is not None:
        prediction_score -= max(0, float(target_ctx["supply_chain_risk_score"]) - 50) * 0.06

    if target_ctx["competitive_risk_score"] is not None:
        prediction_score -= max(0, float(target_ctx["competitive_risk_score"]) - 50) * 0.05

    prediction_score = round(clamp(prediction_score), 2)

    sample_size = len(top)
    closed_sample_size = len(with_closed)
    confidence = confidence_from_sample(closed_sample_size if closed_sample_size else sample_size)

    best_reasons = []
    for m in top[:5]:
        best_reasons.extend(m["reasons"][:5])
    basis = ", ".join(sorted(set(best_reasons))) or "broad context similarity"

    reason = (
        f"Matched {sample_size} historical context rows"
        f" ({closed_sample_size} with closed trades). "
    )

    if probability_of_profit is not None:
        reason += (
            f"Historical profit probability={probability_of_profit:.1%}, "
            f"expected_pnl=${expected_pnl:+.2f}."
        )
    else:
        reason += "No closed-trade outcome sample yet; prediction is mostly context-based."

    return {
        "prediction_score": prediction_score,
        "probability_of_profit": probability_of_profit,
        "probability_of_approval": probability_of_approval,
        "probability_of_order": probability_of_order,
        "expected_pnl": expected_pnl,
        "expected_win_rate": expected_win_rate,
        "confidence": confidence,
        "sample_size": sample_size,
        "similarity_basis": basis,
        "reason": reason,
        "raw": {
            "top_matches": [
                {
                    "market_date": m["context"]["market_date"],
                    "symbol": m["context"]["symbol"],
                    "similarity_score": m["similarity_score"],
                    "reasons": m["reasons"],
                    "outcome": m["outcome"],
                }
                for m in top[:10]
            ],
        },
    }


def predict_symbol(market_date: str, symbol: str, db_path: Path | str = DB_PATH) -> dict:
    init_prediction_tables(db_path)

    symbol = symbol.upper()

    with get_connection(db_path) as con:
        target_ctx = load_target_context(con, market_date, symbol)
        if not target_ctx:
            raise ValueError(f"No daily_symbol_context for {market_date} {symbol}")

        target_events = load_target_events(con, market_date, symbol)
        historical_contexts = load_historical_contexts(con, market_date)

        matches = []
        for hist_ctx in historical_contexts:
            hist_events = events_for_context(con, hist_ctx["market_date"], hist_ctx["symbol"])
            sim_score, reasons = similarity_score(target_ctx, target_events, hist_ctx, hist_events)

            if sim_score <= 0:
                continue

            outcome = outcome_for_context(con, hist_ctx["market_date"], hist_ctx["symbol"])

            matches.append({
                "similarity_score": sim_score,
                "reasons": reasons,
                "context": dict(hist_ctx),
                "outcome": outcome,
            })

    pred = prediction_from_matches(target_ctx, matches)

    return {
        "market_date": market_date,
        "symbol": symbol,
        **{k: v for k, v in pred.items() if k != "raw"},
        "raw": pred["raw"],
    }


def upsert_prediction(prediction: dict, db_path: Path | str = DB_PATH) -> None:
    init_prediction_tables(db_path)

    now = datetime.now().isoformat(timespec="seconds")
    row = {
        "market_date": prediction["market_date"],
        "symbol": prediction["symbol"],
        "prediction_score": prediction.get("prediction_score"),
        "probability_of_profit": prediction.get("probability_of_profit"),
        "probability_of_approval": prediction.get("probability_of_approval"),
        "probability_of_order": prediction.get("probability_of_order"),
        "expected_pnl": prediction.get("expected_pnl"),
        "expected_win_rate": prediction.get("expected_win_rate"),
        "confidence": prediction.get("confidence"),
        "sample_size": prediction.get("sample_size"),
        "similarity_basis": prediction.get("similarity_basis"),
        "reason": prediction.get("reason"),
        "raw_json": json.dumps(prediction.get("raw") or {}, sort_keys=True),
        "created_at": now,
        "updated_at": now,
    }

    cols = PREDICTION_COLUMNS
    values = [row.get(c) for c in cols]
    placeholders = ", ".join(["?"] * len(cols))
    update_cols = [c for c in cols if c not in ("market_date", "symbol", "created_at")]
    update_sql = ", ".join(f"{c}=excluded.{c}" for c in update_cols)

    with get_connection(db_path) as con:
        con.execute(
            f"""
            INSERT INTO daily_symbol_predictions ({", ".join(cols)})
            VALUES ({placeholders})
            ON CONFLICT(market_date, symbol)
            DO UPDATE SET {update_sql}
            """,
            values,
        )


def predict_all_symbols(market_date: str, symbol: str | None = None, write: bool = True) -> list[dict]:
    init_prediction_tables()

    with get_connection(DB_PATH) as con:
        if symbol:
            symbols = [symbol.upper()]
        else:
            rows = con.execute(
                """
                SELECT symbol
                FROM daily_symbol_context
                WHERE market_date = ?
                ORDER BY symbol
                """,
                (market_date,),
            ).fetchall()
            symbols = [r["symbol"] for r in rows]

    predictions = []
    for sym in symbols:
        pred = predict_symbol(market_date, sym)
        predictions.append(pred)
        if write:
            upsert_prediction(pred)

    return predictions
