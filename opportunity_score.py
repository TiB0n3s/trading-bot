"""
Live opportunity scoring gate for BUY signals.

This is active in paper trading. It converts the bot's existing context into a
0-100 score, a block/pass decision, and a size multiplier. Sells bypass this.
"""

from __future__ import annotations

from datetime import datetime


def _num(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _lower(value):
    return str(value or "").strip().lower()


def _trend_staleness_hours(last_time_str):
    """Return age in hours for a 'YYYY-MM-DD HH:MM:SS' timestamp, or None."""
    if not last_time_str:
        return None
    try:
        delta = datetime.now() - datetime.strptime(str(last_time_str), "%Y-%m-%d %H:%M:%S")
        return delta.total_seconds() / 3600.0
    except Exception:
        return None


def _apply_trend_staleness(direction, strength, last_time_str):
    """Downgrade trend strength when last signal is stale."""
    age_hours = _trend_staleness_hours(last_time_str)
    if age_hours is None:
        return direction, strength
    if age_hours > 24:
        return "neutral", "weak"
    if age_hours > 4 and strength == "confirmed":
        return direction, "developing"
    return direction, strength


def _current_position_for(symbol, account_state):
    for p in account_state.get("open_positions") or []:
        if str(p.get("symbol", "")).upper() == symbol.upper():
            return p
    return None


def score_buy_opportunity(symbol, signal_data, account_state):
    """Return a deterministic opportunity score for a BUY signal.

    Output:
      {
        score: 0-100,
        bucket: "blocked"|"weak"|"marginal"|"good"|"strong",
        decision: "block"|"pass",
        size_multiplier: float,
        reason_codes: list[str],
        summary: str
      }
    """
    symbol = str(symbol or "").upper()
    score = 50
    reasons = []

    trend = (account_state.get("trend_table") or {}).get(symbol, {}) or {}
    direction = _lower(trend.get("direction"))
    strength = _lower(trend.get("strength"))
    count = int(_num(trend.get("consecutive_count"), 0))
    direction, strength = _apply_trend_staleness(direction, strength, trend.get("last_time"))

    if direction == "bullish" and strength == "confirmed":
        score += 25
        reasons.append("trend_bullish_confirmed")
    elif direction == "bullish" and strength == "developing":
        score += 15
        reasons.append("trend_bullish_developing")
    elif direction == "bullish":
        score += 8
        reasons.append("trend_bullish")
    elif direction == "neutral":
        score -= 8
        reasons.append("trend_neutral")
    elif direction == "bearish":
        score -= 35
        reasons.append("trend_bearish")

    if count >= 5:
        score += 5
        reasons.append("trend_count_5_plus")

    momentum = account_state.get("momentum") or {}
    m_dir = _lower(momentum.get("direction"))
    m_pct = _num(momentum.get("momentum_pct"), 0.0)

    if m_dir == "rising":
        score += 15
        reasons.append("momentum_rising")
    elif m_dir == "falling":
        if m_pct < -0.15:
            score -= 20
            reasons.append("momentum_falling_hard")
        else:
            score -= 10
            reasons.append("momentum_falling")
    elif m_dir == "flat":
        reasons.append("momentum_flat")

    alignment = _lower(momentum.get("premarket_alignment"))
    if alignment == "confirmed":
        score += 8
        reasons.append("premarket_alignment_confirmed")
    elif alignment == "contradicted":
        score -= 15
        reasons.append("premarket_alignment_contradicted")
    elif alignment == "mixed":
        score -= 5
        reasons.append("premarket_alignment_mixed")

    session = account_state.get("session_momentum") or {}
    session_label = _lower(session.get("trend_label"))
    if session_label in ("strong_uptrend", "developing_uptrend"):
        score += 10
        reasons.append(f"session_{session_label}")
    elif session_label == "reversal_attempt":
        score += 4
        reasons.append("session_reversal_attempt")
    elif session_label in ("fading", "downtrend"):
        score -= 15
        reasons.append(f"session_{session_label}")
    elif session_label == "rangebound":
        score -= 3
        reasons.append("session_rangebound")

    rolling = account_state.get("rolling_momentum") or {}
    if rolling.get("fresh") is True:
        rc = _lower(rolling.get("trend_context"))
        labels = [_lower(x) for x in (rolling.get("special_labels") or [])]

        if rc in ("strong_bullish_continuation", "bullish_continuation"):
            score += 8
            reasons.append(f"rolling_{rc}")
        elif rc in ("bearish_pressure", "bearish_continuation"):
            score -= 12
            reasons.append(f"rolling_{rc}")

        if "gap_up_chase_risk" in labels:
            score -= 12
            reasons.append("rolling_gap_up_chase_risk")
        if "pullback_in_uptrend" in labels:
            score += 4
            reasons.append("rolling_pullback_in_uptrend")
        if "overnight_contradiction" in labels:
            score -= 8
            reasons.append("rolling_overnight_contradiction")
        if "after_hours_warning" in labels:
            score -= 8
            reasons.append("rolling_after_hours_warning")

    market_bias = _lower(account_state.get("market_bias"))
    market_bias_effective = _lower(account_state.get("market_bias_effective"))

    if market_bias == "buy":
        score += 10
        reasons.append("market_bias_buy")

    if market_bias_effective == "avoid_hard":
        score -= 100
        reasons.append("effective_bias_avoid_hard")
    elif market_bias_effective == "avoid_soft":
        score -= 18
        reasons.append("effective_bias_avoid_soft")
    elif market_bias_effective == "live_override_buy":
        score += 5
        reasons.append("effective_bias_live_override_buy")
    elif market_bias_effective == "live_override_neutral":
        score -= 8
        reasons.append("effective_bias_live_override_neutral")

    fundamental = _lower(account_state.get("fundamental_score"))
    if fundamental == "strong_bullish":
        score += 8
        reasons.append("fundamental_strong_bullish")
    elif fundamental == "bullish":
        score += 4
        reasons.append("fundamental_bullish")
    elif fundamental in ("bearish", "strong_bearish"):
        score -= 100
        reasons.append(f"fundamental_{fundamental}")

    risk_level = _lower(account_state.get("risk_level"))
    if risk_level == "very_high":
        score -= 15
        reasons.append("risk_very_high")
    elif risk_level == "high":
        score -= 10
        reasons.append("risk_high")

    entry_quality = _lower(account_state.get("entry_quality"))
    if entry_quality in ("excellent", "high"):
        score += 8
        reasons.append(f"entry_{entry_quality}")
    elif entry_quality in ("good_on_pullbacks", "good_if_holds_gap", "good_if_breadth_holds"):
        score -= 5
        reasons.append(f"entry_conditional_{entry_quality}")
    elif entry_quality in ("tactical_only", "hedge_only", "conditional"):
        score -= 12
        reasons.append(f"entry_{entry_quality}")
    elif entry_quality in ("poor", "do_not_chase", "avoid_chasing"):
        score -= 100
        reasons.append(f"entry_{entry_quality}")

    portfolio = account_state.get("portfolio_stress") or {}
    heat = _lower(portfolio.get("portfolio_heat"))
    if heat == "positive":
        score += 5
        reasons.append("portfolio_positive")
    elif heat == "elevated":
        score -= 10
        reasons.append("portfolio_elevated")
    elif heat == "stressed":
        score -= 20
        reasons.append("portfolio_stressed")

    pos = _current_position_for(symbol, account_state)
    if pos:
        upl_pct = _num(pos.get("unrealized_pl_pct"), 0.0)
        if upl_pct < 0:
            score -= 15
            reasons.append("adding_to_loser")
        elif upl_pct > 1.0:
            score -= 10
            reasons.append("pyramiding_winner_over_1pct")
        else:
            score -= 5
            reasons.append("already_has_position")

    session_elapsed = _num(account_state.get("session_elapsed_minutes"), None)
    minutes_until_close = _num(account_state.get("minutes_until_close"), None)

    if minutes_until_close is not None and minutes_until_close < 20:
        score -= 100
        reasons.append("too_close_to_close")
    elif minutes_until_close is not None and minutes_until_close < 45:
        score -= 12
        reasons.append("late_session_caution")

    if session_elapsed is not None and session_elapsed < 15:
        score -= 8
        reasons.append("early_session_caution")

    history = account_state.get("symbol_history") or {}
    sample_size = int(_num(history.get("sample_size"), 0))
    win_rate = _num(history.get("win_rate"), None)
    setup_wr = _num(history.get("current_setup_win_rate"), None)
    setup_sample = int(_num(history.get("current_setup_sample"), 0))

    if sample_size >= 5 and win_rate is not None:
        if win_rate >= 0.65:
            score += 8
            reasons.append("symbol_history_strong")
        elif win_rate <= 0.35:
            score -= 12
            reasons.append("symbol_history_weak")

    if setup_sample >= 2 and setup_wr is not None:
        if setup_wr >= 0.65:
            score += 6
            reasons.append("setup_history_strong")
        elif setup_wr <= 0.35:
            score -= 8
            reasons.append("setup_history_weak")

    last_5 = history.get("last_5_outcomes") or []
    if len(last_5) >= 5 and all(x == "loss" for x in last_5[:5]):
        score -= 15
        reasons.append("symbol_losing_streak")

    avg_loss_pct = history.get("avg_loss_pct")
    if avg_loss_pct is not None and _num(avg_loss_pct) < -1.5:
        score -= 6
        reasons.append("symbol_large_avg_loss")

    score = max(0, min(100, int(round(score))))

    # Active live-in-paper policy.
    if score < 45:
        decision = "block"
    else:
        decision = "pass"

    if score >= 75:
        bucket = "strong"
        size_multiplier = 1.00
    elif score >= 60:
        bucket = "good"
        size_multiplier = 0.85
    elif score >= 45:
        bucket = "marginal"
        size_multiplier = 0.60
    elif score >= 30:
        bucket = "weak"
        size_multiplier = 0.00
    else:
        bucket = "blocked"
        size_multiplier = 0.00

    summary = f"score={score} bucket={bucket} decision={decision} reasons={','.join(reasons[:8])}"

    return {
        "score": score,
        "bucket": bucket,
        "decision": decision,
        "size_multiplier": size_multiplier,
        "reason_codes": reasons,
        "summary": summary[:500],
    }
