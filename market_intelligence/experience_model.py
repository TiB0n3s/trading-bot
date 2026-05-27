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
    "timing_score",
    "recommended_entry_timing",
    "recommended_exit_timing",
    "historical_avg_entry_delay",
    "historical_avg_exit_delay",
    "historical_timing_sample_size",
    "timing_reason",
    "trend_score",
    "trend_label",
    "trend_regime",
    "trend_confidence",
    "trend_similarity_sample_size",
    "trend_reason",
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

                timing_score REAL,
                recommended_entry_timing TEXT,
                recommended_exit_timing TEXT,
                historical_avg_entry_delay REAL,
                historical_avg_exit_delay REAL,
                historical_timing_sample_size INTEGER,
                timing_reason TEXT,

                trend_score REAL,
                trend_label TEXT,
                trend_regime TEXT,
                trend_confidence TEXT,
                trend_similarity_sample_size INTEGER,
                trend_reason TEXT,

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

        # Add timing columns for existing databases.
        existing_cols = {
            row["name"]
            for row in con.execute("PRAGMA table_info(daily_symbol_predictions)").fetchall()
        }
        timing_columns = {
            "timing_score": "REAL",
            "recommended_entry_timing": "TEXT",
            "recommended_exit_timing": "TEXT",
            "historical_avg_entry_delay": "REAL",
            "historical_avg_exit_delay": "REAL",
            "historical_timing_sample_size": "INTEGER",
            "timing_reason": "TEXT",
            "trend_score": "REAL",
            "trend_label": "TEXT",
            "trend_regime": "TEXT",
            "trend_confidence": "TEXT",
            "trend_similarity_sample_size": "INTEGER",
            "trend_reason": "TEXT",
        }
        for col, col_type in timing_columns.items():
            if col not in existing_cols:
                con.execute(f"ALTER TABLE daily_symbol_predictions ADD COLUMN {col} {col_type}")


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
    """Return trade/outcome stats for a symbol/date.

    Uses live trades/matched_trades when present, plus learning-only historical
    tables rebuilt from Alpaca exports and signal logs.
    """
    try:
        trades = con.execute(
            """
            SELECT *
            FROM trades
            WHERE timestamp LIKE ?
              AND symbol = ?
            """,
            (f"{market_date}%", symbol),
        ).fetchall()
    except Exception:
        trades = []

    signals = len(trades)
    approved = sum(1 for r in trades if int(r["approved"] or 0) == 1)
    orders = sum(1 for r in trades if r["order_id"])
    filled = sum(
        1 for r in trades
        if r["order_status"] in ("filled", "partially_filled")
        and r["fill_price"] is not None
    )

    # Add deduped historical signal events when live trades rows are missing due to DB rebuild.
    hist_signals = []
    try:
        hist_signals = con.execute(
            """
            SELECT *
            FROM historical_signal_events
            WHERE market_date = ?
              AND symbol = ?
            """,
            (market_date, symbol),
        ).fetchall()
    except Exception:
        hist_signals = []

    # Fallback to raw signal experience if deduped events are not built yet.
    if not hist_signals:
        try:
            hist_signals = con.execute(
                """
                SELECT *
                FROM historical_signal_experience
                WHERE market_date = ?
                  AND symbol = ?
                  AND decision_summary IN ('signal_received', 'processing_signal', 'order_placed')
                """,
                (market_date, symbol),
            ).fetchall()
        except Exception:
            hist_signals = []

    if not signals and hist_signals:
        signals = len(hist_signals)
        approved = sum(1 for r in hist_signals if int(r["approved"] or 0) == 1)
        orders = sum(1 for r in hist_signals if (r["order_id"] or r["decision_summary"] == "order_placed"))
        filled = orders

    matched = []
    try:
        matched = con.execute(
            """
            SELECT realized_pnl, realized_pnl_pct
            FROM matched_trades
            WHERE exit_timestamp LIKE ?
              AND symbol = ?
            """,
            (f"{market_date}%", symbol),
        ).fetchall()
    except Exception:
        matched = []

    hist_outcomes = []
    try:
        hist_outcomes = con.execute(
            """
            SELECT realized_pnl, realized_pnl_pct
            FROM historical_trade_outcomes
            WHERE exit_timestamp LIKE ?
              AND symbol = ?
            """,
            (f"{market_date}%", symbol),
        ).fetchall()
    except Exception:
        hist_outcomes = []

    # Prefer live matched_trades; only fall back to historical_trade_outcomes when
    # no live match rows exist for this date (avoids double-counting the same exit).
    closed_rows = list(matched) if matched else list(hist_outcomes)

    closed = len(closed_rows)
    pnl = sum(float(r["realized_pnl"] or 0) for r in closed_rows)
    wins = sum(1 for r in closed_rows if float(r["realized_pnl"] or 0) > 0)

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
        # Deliberately visible because same-symbol weighting can dominate sparse
        # histories. Review this once enough post-QA rows exist per symbol.
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



def _timing_recommendation_from_row(row):
    """Map aggregate timing stats into deterministic observe-only guidance."""
    matched = int(row["matched"] or 0)
    action = row["action"]
    bucket = str(row["bucket"] or "")
    avg_pnl = float(row["avg_pnl"] or 0)
    total_pnl = float(row["total_pnl"] or 0)

    if matched < 3:
        return "watch_more_data", 50.0

    if action == "buy":
        if "immediate_entry" in bucket and avg_pnl > 0:
            return "allow_immediate_if_context_confirms", 65.0
        if "immediate_entry" in bucket and avg_pnl < 0:
            return "avoid_immediate_entry_or_require_confirmation", 35.0
        if "delayed_entry" in bucket and avg_pnl > 0:
            return "prefer_wait_for_confirmation", 62.0
        if "very_late_entry" in bucket and avg_pnl < 0:
            return "avoid_late_chasing", 30.0
        if total_pnl > 0:
            return "setup_has_positive_timing_expectancy", 60.0
        return "setup_timing_needs_caution", 42.0

    if action == "sell":
        if "immediate_exit" in bucket and avg_pnl > 0:
            return "sell_signal_exit_timing_good", 65.0
        if "delayed_exit" in bucket and avg_pnl < 0:
            return "consider_faster_exit", 38.0
        if total_pnl > 0:
            return "sell_context_generally_profitable", 58.0
        return "sell_timing_needs_review", 45.0

    return "review_timing", 50.0



def trend_context_for_symbol(con, market_date: str, symbol: str):
    try:
        return con.execute(
            """
            SELECT *
            FROM historical_trend_context
            WHERE market_date = ?
              AND symbol = ?
            """,
            (market_date, symbol),
        ).fetchone()
    except Exception:
        return None


def trend_similarity_lesson(con, market_date: str, symbol: str) -> dict:
    """Return observe-only trend score using historical trend contexts + signal outcomes.

    Finds prior symbol/date rows with the same trend_label/regime when possible,
    then summarizes linked historical_signal_outcomes by date+symbol.
    """
    target = trend_context_for_symbol(con, market_date, symbol)

    if not target:
        return {
            "trend_score": 50.0,
            "trend_label": None,
            "trend_regime": None,
            "trend_confidence": None,
            "trend_similarity_sample_size": 0,
            "trend_reason": "No historical_trend_context row available for this symbol/date.",
        }

    try:
        rows = con.execute(
            """
            SELECT
                t.market_date,
                t.symbol,
                t.trend_label,
                t.trend_regime,
                t.relative_strength_score,
                t.distance_from_sma_20_pct,
                COUNT(s.id) AS signal_rows,
                SUM(CASE WHEN s.matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched_signals,
                SUM(CASE WHEN s.realized_pnl > 0 THEN 1 ELSE 0 END) AS winners,
                SUM(CASE WHEN s.realized_pnl < 0 THEN 1 ELSE 0 END) AS losers,
                AVG(s.realized_pnl) AS avg_pnl,
                SUM(s.realized_pnl) AS total_pnl,
                AVG(s.realized_pnl_pct) AS avg_pnl_pct
            FROM historical_trend_context t
            LEFT JOIN historical_signal_outcomes s
              ON s.market_date = t.market_date
             AND s.symbol = t.symbol
            WHERE t.market_date < ?
              AND (
                    t.trend_label = ?
                 OR t.trend_regime = ?
                 OR t.symbol = ?
              )
            GROUP BY t.market_date, t.symbol
            HAVING matched_signals > 0
            ORDER BY
              CASE WHEN t.symbol = ? THEN 0 ELSE 1 END,
              CASE WHEN t.trend_label = ? THEN 0 ELSE 1 END,
              t.market_date DESC
            LIMIT 40
            """,
            (
                market_date,
                target["trend_label"],
                target["trend_regime"],
                symbol,
                symbol,
                target["trend_label"],
            ),
        ).fetchall()
    except Exception as e:
        return {
            "trend_score": 50.0,
            "trend_label": target["trend_label"],
            "trend_regime": target["trend_regime"],
            "trend_confidence": target["trend_confidence"],
            "trend_similarity_sample_size": 0,
            "trend_reason": f"Trend similarity lookup failed: {e}",
        }

    if not rows:
        return {
            "trend_score": 50.0,
            "trend_label": target["trend_label"],
            "trend_regime": target["trend_regime"],
            "trend_confidence": target["trend_confidence"],
            "trend_similarity_sample_size": 0,
            "trend_reason": (
                f"No prior matched signal outcomes for trend_label={target['trend_label']} "
                f"or trend_regime={target['trend_regime']}."
            ),
        }

    matched = sum(int(r["matched_signals"] or 0) for r in rows)
    winners = sum(int(r["winners"] or 0) for r in rows)
    total_pnl = sum(float(r["total_pnl"] or 0) for r in rows)
    avg_pnl = total_pnl / matched if matched else 0.0
    win_rate = winners / matched if matched else 0.0

    score = 50.0
    score += (win_rate - 0.5) * 35.0
    score += max(-15.0, min(15.0, avg_pnl * 2.5))

    # Modest adjustment from current trend shape.
    if target["trend_label"] == "confirmed_uptrend":
        score += 4
    elif target["trend_label"] == "uptrend_pullback":
        score += 3
    elif target["trend_label"] == "extended_uptrend":
        score -= 4
    elif target["trend_label"] == "downtrend":
        score -= 8
    elif target["trend_label"] == "volatile_unclear":
        score -= 5

    score = round(clamp(score), 2)

    return {
        "trend_score": score,
        "trend_label": target["trend_label"],
        "trend_regime": target["trend_regime"],
        "trend_confidence": target["trend_confidence"],
        "trend_similarity_sample_size": matched,
        "trend_reason": (
            f"trend_label={target['trend_label']} regime={target['trend_regime']} "
            f"matched_signals={matched} win_rate={win_rate:.1%} "
            f"avg_pnl=${avg_pnl:+.2f} total_pnl=${total_pnl:+.2f}; "
            f"current_reason={target['trend_reason']}"
        ),
    }



def timing_lesson_for_symbol(con, market_date: str, symbol: str) -> dict:
    """Return observe-only timing lesson from historical_signal_outcomes.

    Preference order:
    1. symbol-specific buy timing
    2. all-symbol buy timing
    3. no data
    """
    def fetch(symbol_filter: bool):
        params = []
        where = ["action = 'buy'", "market_date <= ?"]
        params.append(market_date)

        if symbol_filter:
            where.append("symbol = ?")
            params.append(symbol)

        where_sql = " AND ".join(where)

        return con.execute(
            f"""
            SELECT
              entry_timing_label AS bucket,
              action,
              COUNT(*) AS n,
              SUM(CASE WHEN matched_outcome_id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
              ROUND(AVG(entry_delay_minutes), 2) AS avg_entry_delay,
              ROUND(AVG(exit_delay_minutes), 2) AS avg_exit_delay,
              ROUND(AVG(realized_pnl), 4) AS avg_pnl,
              ROUND(SUM(realized_pnl), 4) AS total_pnl,
              ROUND(AVG(realized_pnl_pct), 4) AS avg_pnl_pct
            FROM historical_signal_outcomes
            WHERE {where_sql}
            GROUP BY entry_timing_label, action
            HAVING matched > 0
            ORDER BY total_pnl DESC, matched DESC
            LIMIT 1
            """,
            params,
        ).fetchone()

    try:
        row = fetch(symbol_filter=True)
    except Exception:
        row = None

    scope = "symbol_specific"
    if not row:
        try:
            row = fetch(symbol_filter=False)
            scope = "global_buy_timing"
        except Exception:
            row = None

    if not row:
        return {
            "timing_score": 50.0,
            "recommended_entry_timing": "watch_more_data",
            "recommended_exit_timing": None,
            "historical_avg_entry_delay": None,
            "historical_avg_exit_delay": None,
            "historical_timing_sample_size": 0,
            "timing_reason": "No historical signal timing outcomes available yet.",
        }

    rec, score = _timing_recommendation_from_row(row)

    return {
        "timing_score": score,
        "recommended_entry_timing": rec,
        "recommended_exit_timing": None,
        "historical_avg_entry_delay": row["avg_entry_delay"],
        "historical_avg_exit_delay": row["avg_exit_delay"],
        "historical_timing_sample_size": int(row["matched"] or 0),
        "timing_reason": (
            f"{scope}: best historical buy timing bucket={row['bucket']} "
            f"matched={row['matched']} avg_pnl={row['avg_pnl']} "
            f"total_pnl={row['total_pnl']} avg_entry_delay={row['avg_entry_delay']}m"
        ),
    }



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

    with get_connection(db_path) as con:
        timing = timing_lesson_for_symbol(con, market_date, symbol)
        trend = trend_similarity_lesson(con, market_date, symbol)

    # Gentle observe-only score blend: trend/timing should inform, not dominate.
    base_score = float(pred.get("prediction_score") or 50.0)
    timing_score = float(timing.get("timing_score") or 50.0)
    trend_score = float(trend.get("trend_score") or 50.0)
    blended_score = round(clamp((base_score * 0.70) + (timing_score * 0.15) + (trend_score * 0.15)), 2)
    pred["prediction_score"] = blended_score

    combined_raw = pred["raw"]
    combined_raw["timing_lesson"] = timing
    combined_raw["trend_lesson"] = trend
    combined_raw["base_prediction_score_before_timing_trend_blend"] = base_score

    return {
        "market_date": market_date,
        "symbol": symbol,
        **{k: v for k, v in pred.items() if k != "raw"},
        **timing,
        **trend,
        "raw": combined_raw,
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
        "timing_score": prediction.get("timing_score"),
        "recommended_entry_timing": prediction.get("recommended_entry_timing"),
        "recommended_exit_timing": prediction.get("recommended_exit_timing"),
        "historical_avg_entry_delay": prediction.get("historical_avg_entry_delay"),
        "historical_avg_exit_delay": prediction.get("historical_avg_exit_delay"),
        "historical_timing_sample_size": prediction.get("historical_timing_sample_size"),
        "timing_reason": prediction.get("timing_reason"),
        "trend_score": prediction.get("trend_score"),
        "trend_label": prediction.get("trend_label"),
        "trend_regime": prediction.get("trend_regime"),
        "trend_confidence": prediction.get("trend_confidence"),
        "trend_similarity_sample_size": prediction.get("trend_similarity_sample_size"),
        "trend_reason": prediction.get("trend_reason"),
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
