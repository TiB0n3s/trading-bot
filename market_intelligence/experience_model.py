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

from build_historical_trend_context import ensure_historical_trend_context_table
from market_intelligence.intelligence_store import init_intelligence_tables
from repositories.experience_model_repo import ExperienceModelRepository


DB_PATH = Path(__file__).resolve().parents[1] / "trades.db"


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
    ensure_historical_trend_context_table(db_path)

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
    ExperienceModelRepository(db_path).init_prediction_tables(timing_columns)


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


def load_target_context(repo: ExperienceModelRepository, market_date: str, symbol: str):
    return repo.load_target_context(market_date, symbol)


def load_target_events(repo: ExperienceModelRepository, market_date: str, symbol: str):
    return repo.load_target_events(market_date, symbol)


def load_historical_contexts(
    repo: ExperienceModelRepository,
    market_date: str,
    symbol: str | None = None,
):
    return repo.load_historical_contexts(market_date, symbol)


def events_for_context(repo: ExperienceModelRepository, market_date: str, symbol: str):
    return repo.events_for_context(market_date, symbol)


def outcome_for_context(repo: ExperienceModelRepository, market_date: str, symbol: str):
    """Return trade/outcome stats for a symbol/date.

    Uses live trades/matched_trades when present, plus learning-only historical
    tables rebuilt from Alpaca exports and signal logs.
    """
    try:
        trades = repo.trade_rows_for_context(market_date, symbol)
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
        hist_signals = repo.historical_signal_event_rows(market_date, symbol)
    except Exception:
        hist_signals = []

    # Fallback to raw signal experience if deduped events are not built yet.
    if not hist_signals:
        try:
            hist_signals = repo.historical_signal_experience_rows(market_date, symbol)
        except Exception:
            hist_signals = []

    if not signals and hist_signals:
        signals = len(hist_signals)
        approved = sum(1 for r in hist_signals if int(r["approved"] or 0) == 1)
        orders = sum(1 for r in hist_signals if (r["order_id"] or r["decision_summary"] == "order_placed"))
        filled = orders

    matched = []
    try:
        matched = repo.matched_trade_rows_for_context(market_date, symbol)
    except Exception:
        matched = []

    hist_outcomes = []
    try:
        hist_outcomes = repo.historical_trade_outcome_rows(market_date, symbol)
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



def trend_context_for_symbol(repo: ExperienceModelRepository, market_date: str, symbol: str):
    try:
        return repo.trend_context_for_symbol(market_date, symbol)
    except Exception:
        return None


def trend_similarity_lesson(repo: ExperienceModelRepository, market_date: str, symbol: str) -> dict:
    """Return observe-only trend score using historical trend contexts + signal outcomes.

    Finds prior symbol/date rows with the same trend_label/regime when possible,
    then summarizes linked historical_signal_outcomes by date+symbol.
    """
    target = trend_context_for_symbol(repo, market_date, symbol)

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
        rows = repo.trend_similarity_rows(market_date, symbol, target)
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



def timing_lesson_for_symbol(repo: ExperienceModelRepository, market_date: str, symbol: str) -> dict:
    """Return observe-only timing lesson from historical_signal_outcomes.

    Preference order:
    1. symbol-specific buy timing
    2. all-symbol buy timing
    3. no data
    """
    try:
        row = repo.timing_lesson_row(market_date, symbol, symbol_filter=True)
    except Exception:
        row = None

    scope = "symbol_specific"
    if not row:
        try:
            row = repo.timing_lesson_row(market_date, symbol, symbol_filter=False)
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


def weekly_symbol_performance(market_date: str, symbol: str, db_path: Path | str = DB_PATH) -> dict:
    """Return bounded current-week symbol performance modifier.

    Uses realized matched trades from the current week up to market_date.
    This is a soft modifier only; it must not override hard risk controls.
    """
    try:
        row = ExperienceModelRepository(db_path).weekly_symbol_performance_row(
            market_date,
            symbol,
        )

        trades = int(row["trades"] or 0) if row else 0
        wins = int(row["wins"] or 0) if row else 0
        losses = int(row["losses"] or 0) if row else 0
        pnl = float(row["pnl"] or 0.0) if row else 0.0
        expectancy = float(row["expectancy"] or 0.0) if row else 0.0
        avg_pnl_pct = float(row["avg_pnl_pct"] or 0.0) if row else 0.0
        win_rate = (wins / trades) if trades else 0.0

        label = "neutral"
        modifier = 0.0

        if trades >= 3 and expectancy > 0 and win_rate >= 0.75:
            label = "strong_weekly_boost"
            modifier = 6.0
        elif trades >= 2 and expectancy > 0 and win_rate >= 0.50:
            label = "weekly_boost"
            modifier = 4.0
        elif trades >= 2 and (expectancy < 0 or win_rate < 0.35):
            label = "weekly_penalty"
            modifier = -6.0

        reason = (
            f"weekly_symbol_performance={label}; "
            f"trades={trades}; wins={wins}; losses={losses}; "
            f"win_rate={win_rate:.1%}; pnl=${pnl:+.2f}; "
            f"expectancy=${expectancy:+.2f}; modifier={modifier:+.1f}"
        )

        return {
            "label": label,
            "modifier": modifier,
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "pnl": pnl,
            "expectancy": expectancy,
            "avg_pnl_pct": avg_pnl_pct,
            "reason": reason,
        }

    except Exception as e:
        return {
            "label": "error",
            "modifier": 0.0,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "pnl": 0.0,
            "expectancy": 0.0,
            "avg_pnl_pct": 0.0,
            "reason": f"weekly_symbol_performance_error={e}",
        }

def predict_symbol(market_date: str, symbol: str, db_path: Path | str = DB_PATH) -> dict:
    init_prediction_tables(db_path)

    symbol = symbol.upper()
    repo = ExperienceModelRepository(db_path)

    target_ctx = load_target_context(repo, market_date, symbol)
    if not target_ctx:
        raise ValueError(f"No daily_symbol_context for {market_date} {symbol}")

    target_events = load_target_events(repo, market_date, symbol)
    historical_contexts = load_historical_contexts(repo, market_date)

    matches = []
    for hist_ctx in historical_contexts:
        hist_events = events_for_context(repo, hist_ctx["market_date"], hist_ctx["symbol"])
        sim_score, reasons = similarity_score(target_ctx, target_events, hist_ctx, hist_events)

        if sim_score <= 0:
            continue

        outcome = outcome_for_context(repo, hist_ctx["market_date"], hist_ctx["symbol"])

        matches.append({
            "similarity_score": sim_score,
            "reasons": reasons,
            "context": dict(hist_ctx),
            "outcome": outcome,
        })

    pred = prediction_from_matches(target_ctx, matches)

    timing = timing_lesson_for_symbol(repo, market_date, symbol)
    trend = trend_similarity_lesson(repo, market_date, symbol)

    # Gentle observe-only score blend: trend/timing should inform, not dominate.
    base_score = float(pred.get("prediction_score") or 50.0)
    timing_score = float(timing.get("timing_score") or 50.0)
    trend_score = float(trend.get("trend_score") or 50.0)
    weekly = weekly_symbol_performance(market_date, symbol, db_path=db_path)

    pre_weekly_score = round(
        clamp((base_score * 0.70) + (timing_score * 0.15) + (trend_score * 0.15)),
        2,
    )
    weekly_modifier = float(weekly.get("modifier") or 0.0)
    blended_score = round(clamp(pre_weekly_score + weekly_modifier), 2)
    pred["prediction_score"] = blended_score

    weekly_reason = weekly.get("reason")
    if weekly_modifier:
        pred["reason"] = (
            f"{pred.get('reason', '')} "
            f"Weekly performance modifier applied: {weekly_reason}. "
        ).strip()
    else:
        pred["reason"] = (
            f"{pred.get('reason', '')} "
            f"Weekly performance neutral: {weekly_reason}. "
        ).strip()

    combined_raw = pred["raw"]
    combined_raw["timing_lesson"] = timing
    combined_raw["trend_lesson"] = trend
    combined_raw["base_prediction_score_before_timing_trend_blend"] = base_score
    combined_raw["prediction_score_before_weekly_modifier"] = pre_weekly_score
    combined_raw["weekly_symbol_performance"] = weekly

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

    ExperienceModelRepository(db_path).upsert_prediction(row, PREDICTION_COLUMNS)


def predict_all_symbols(market_date: str, symbol: str | None = None, write: bool = True) -> list[dict]:
    init_prediction_tables()

    if symbol:
        symbols = [symbol.upper()]
    else:
        symbols = ExperienceModelRepository(DB_PATH).prediction_symbols(market_date)

    predictions = []
    for sym in symbols:
        pred = predict_symbol(market_date, sym)
        predictions.append(pred)
        if write:
            upsert_prediction(pred)

    return predictions
