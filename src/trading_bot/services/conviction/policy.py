"""Pure decision functions for conviction mode.

Two entry points:

* ``conviction_entry_decision`` — given a ranked candidate plus account/last-trade
  state, decide whether this is a high-conviction entry. All gates are mandatory
  (convergence is enforced by conjunction), and the result carries a per-check
  breakdown so paper sessions are fully explainable.

* ``conviction_exit_decision`` — given the live state of an open position, decide
  hold / trim / exit. Built for a multi-bar hold: a protective hard stop, a
  minimum hold, a high-water trailing stop that lets winners run, an optional
  time stop, and a reversal-protect exit.

Inputs are read defensively (mirroring the ``_to_float`` / ``_dict`` style in the
auto_buy / auto_sell managers) so a missing field degrades to a clear reason
instead of an exception.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoids a hard runtime dependency; cfg is duck-typed
    from config.conviction import ConvictionConfig

PAPER_MODES = {"paper", "dry_run"}


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    return bool(value)


def conviction_active_for_mode(cfg: "ConvictionConfig", execution_mode: str) -> bool:
    """Whether conviction mode should take authority under ``execution_mode``.

    Disabled unless ``cfg.enabled``; when ``cfg.paper_only`` it additionally
    requires a paper/dry-run mode so it cannot affect live/cash execution.
    """
    if not getattr(cfg, "enabled", False):
        return False
    if getattr(cfg, "paper_only", True):
        return str(execution_mode or "").strip().lower() in PAPER_MODES
    return True


def conviction_entry_decision(
    *,
    candidate: dict[str, Any] | None,
    account_state: dict[str, Any] | None,
    last_trade_state: dict[str, Any] | None,
    cfg: "ConvictionConfig",
) -> dict[str, Any]:
    """Decide whether ``candidate`` qualifies as a high-conviction entry.

    Args:
        candidate: ranked candidate. Recognized keys (all optional, read
            defensively): ``symbol``, ``score`` (heuristic composite),
            ``probability_pct`` (learned 0-100), ``probability_source``,
            ``ml_veto`` (bool), ``market_context_ok`` (bool).
        account_state: ``open_positions`` (int).
        last_trade_state: ``minutes_since_last_entry`` (float|None). None means
            no prior entry today -> cooldown treated as satisfied.
        cfg: ConvictionConfig (or any object exposing the same attributes).

    Returns:
        dict with ``enter`` (bool), ``reason`` (first failing gate or
        "conviction_entry_confirmed"), ``checks`` (per-gate booleans), and
        ``conviction_score`` (the candidate score that cleared/failed the bar).
    """
    candidate = candidate if isinstance(candidate, dict) else {}
    account_state = account_state if isinstance(account_state, dict) else {}
    last_trade_state = last_trade_state if isinstance(last_trade_state, dict) else {}

    symbol = candidate.get("symbol")
    score = _to_float(candidate.get("score"), 0.0) or 0.0
    probability_pct = _to_float(candidate.get("probability_pct"), None)
    probability_source = str(candidate.get("probability_source") or "").strip().lower()
    ml_veto = _bool(candidate.get("ml_veto"))
    market_context_ok = _bool(candidate.get("market_context_ok"))

    open_positions = _to_int(account_state.get("open_positions"), 0)
    minutes_since_last_entry = _to_float(last_trade_state.get("minutes_since_last_entry"), None)

    checks: dict[str, bool] = {}

    # --- Scarcity: capacity -------------------------------------------------
    checks["capacity_ok"] = open_positions < int(cfg.max_concurrent_positions)

    # --- Scarcity: refractory period ---------------------------------------
    if minutes_since_last_entry is None:
        checks["cooldown_ok"] = True  # no prior entry to respect
    else:
        checks["cooldown_ok"] = minutes_since_last_entry >= int(cfg.min_minutes_between_entries)

    # --- Quality: heuristic conviction bar ---------------------------------
    checks["score_ok"] = score >= float(cfg.min_score)

    # --- Quality: learned probability bar ----------------------------------
    system_probability_sources = {
        "probability_of_approval",
        "probability_of_order",
        "daily_symbol_predictions:probability_of_approval",
        "daily_symbol_predictions:probability_of_order",
    }
    probability_threshold = (
        float(getattr(cfg, "min_system_probability_pct", cfg.min_probability_pct))
        if probability_source in system_probability_sources
        else float(cfg.min_probability_pct)
    )
    if probability_pct is None:
        checks["probability_ok"] = not bool(cfg.require_probability)
    else:
        checks["probability_ok"] = probability_pct >= probability_threshold

    # --- Risk: ML veto ------------------------------------------------------
    checks["ml_ok"] = not (bool(cfg.block_on_ml_veto) and ml_veto)

    # --- Risk: market context ----------------------------------------------
    checks["market_ok"] = (not bool(cfg.require_market_context_ok)) or market_context_ok

    # First failing gate -> a specific, loggable reason. Order is the order a
    # human would triage: cheapest/structural gates first.
    failure_reasons = [
        ("capacity_ok", "max_concurrent_positions_reached"),
        ("cooldown_ok", "entry_cooldown_active"),
        ("score_ok", "score_below_conviction_bar"),
        (
            "probability_ok",
            "probability_unavailable" if probability_pct is None else "probability_below_bar",
        ),
        ("ml_ok", "ml_veto"),
        ("market_ok", "market_context_unfavorable"),
    ]

    reason = "conviction_entry_confirmed"
    enter = True
    for key, fail_reason in failure_reasons:
        if not checks[key]:
            enter = False
            reason = fail_reason
            break

    return {
        "enter": enter,
        "reason": reason,
        "symbol": symbol,
        "conviction_score": round(score, 4),
        "probability_pct": probability_pct,
        "probability_source": probability_source or None,
        "probability_threshold_pct": probability_threshold,
        "checks": checks,
    }


def conviction_exit_decision(
    *,
    position_state: dict[str, Any] | None,
    cfg: "ConvictionConfig",
) -> dict[str, Any]:
    """Decide hold / trim / exit for an open conviction position.

    Args:
        position_state: recognized keys (read defensively):
            ``unrealized_plpc`` (current P&L percent, e.g. 2.5 for +2.5%),
            ``high_water_plpc`` (peak P&L percent since entry; falls back to
            ``unrealized_plpc`` if absent), ``minutes_held`` (float),
            ``momentum_reversal`` (bool), ``ml_bearish`` (bool).
        cfg: ConvictionConfig (or duck-typed equivalent).

    Returns:
        dict with ``action`` ("hold" | "exit"), ``reason``, and ``trailing``
        (the engaged state and computed floor, for observability).

    Precedence: hard stop > min-hold guard > take-profit ceiling >
    trailing stop > time stop > reversal-protect > hold. The hard stop is
    checked first so a min-hold window can never trap a losing position.
    """
    position_state = position_state if isinstance(position_state, dict) else {}

    unrealized_plpc = _to_float(position_state.get("unrealized_plpc"), 0.0) or 0.0
    high_water_plpc = _to_float(position_state.get("high_water_plpc"), None)
    if high_water_plpc is None:
        high_water_plpc = unrealized_plpc
    high_water_plpc = max(high_water_plpc, unrealized_plpc)
    minutes_held = _to_float(position_state.get("minutes_held"), 0.0) or 0.0
    momentum_reversal = _bool(position_state.get("momentum_reversal"))
    ml_bearish = _bool(position_state.get("ml_bearish"))

    # Trailing floor: engaged only once peak gain clears activation.
    trail_engaged = high_water_plpc >= float(cfg.trail_activate_pct)
    trail_floor = (
        high_water_plpc * (1.0 - float(cfg.trail_giveback_frac)) if trail_engaged else None
    )
    trailing = {
        "engaged": trail_engaged,
        "high_water_plpc": round(high_water_plpc, 4),
        "floor_plpc": round(trail_floor, 4) if trail_floor is not None else None,
        "unrealized_plpc": round(unrealized_plpc, 4),
    }

    def _result(action: str, reason: str) -> dict[str, Any]:
        return {"action": action, "reason": reason, "trailing": trailing}

    # 1) Protective hard stop — always first.
    if unrealized_plpc <= -float(cfg.hard_stop_pct):
        return _result("exit", "hard_stop")

    # 2) Min-hold guard — below this, only the hard stop can fire.
    if minutes_held < float(cfg.min_hold_minutes):
        return _result("hold", "min_hold_active")

    # 3) Optional fixed take-profit ceiling.
    take_profit_pct = float(cfg.take_profit_pct)
    if take_profit_pct > 0 and unrealized_plpc >= take_profit_pct:
        return _result("exit", "take_profit")

    # 4) Trailing stop — let it run, protect the bulk of the move.
    if trail_engaged and trail_floor is not None and unrealized_plpc <= trail_floor:
        return _result("exit", "trailing_stop")

    # 5) Optional time stop.
    max_hold = float(cfg.max_hold_minutes)
    if max_hold > 0 and minutes_held >= max_hold:
        return _result("exit", "time_stop")

    # 6) Reversal-protect — only when in profit, to avoid bailing on noise.
    if bool(cfg.exit_on_reversal) and unrealized_plpc > 0 and (momentum_reversal or ml_bearish):
        return _result("exit", "reversal_protect")

    return _result("hold", "hold")
