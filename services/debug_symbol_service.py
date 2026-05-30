"""Runtime-bound payload builder extracted from app.py.

This is an interim boundary: route code calls this service while the service
resolves runtime dependencies from the Flask composition module.
"""

from __future__ import annotations


def _bind_runtime(runtime):
    globals().update(
        {
            name: value
            for name, value in vars(runtime).items()
            if not name.startswith("__")
        }
    )


def _trend_table_state():
    service = globals().get("_trend_state_service")
    return getattr(service, "trend_table", globals().get("_trend_table", {}))


def _market_bias_state():
    service = globals().get("_market_context_service")
    return getattr(service, "market_bias", globals().get("_market_bias", {}))


def _load_market_bias_state():
    service = globals().get("_market_context_service")
    if service is not None:
        service.load()
    else:
        _load_market_context()


def build_debug_symbol_payload(runtime, symbol):
    _bind_runtime(runtime)
    symbol = symbol.upper()
    if symbol not in APPROVED_SYMBOLS:
        return {
            "error": "symbol not approved",
            "symbol": symbol,
            "approved_symbols": sorted(APPROVED_SYMBOLS),
        }, 400

    _load_market_bias_state()

    now_et_value = now_et()
    market_hours_open = is_market_hours(now_et_value)
    
    result = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "now_et": now_et_value.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "market_hours_open": market_hours_open,
    }

    # Account / circuit breaker
    try:
        state = get_mock_account_state()
        result["account"] = {
            "balance": state.get("balance"),
            "portfolio_value": state.get("portfolio_value"),
            "daily_pnl": state.get("daily_pnl"),
            "daily_pnl_pct": state.get("daily_pnl_pct"),
            "circuit_breaker_active_for_buys": (state.get("daily_pnl_pct") or 0) < DAILY_LOSS_LIMIT_PCT,
            "open_position_count": state.get("open_position_count"),
        }
    except Exception as e:
        result["account_error"] = str(e)
        state = {}

    # Alpaca live position
    try:
        pos = broker_service.get_position(symbol)
        result["alpaca_position"] = pos
        result["has_live_position"] = bool(pos)
    except Exception as e:
        result["alpaca_position_error"] = str(e)

    # Trend snapshot for all approved symbols
    try:
        result["trend_table_summary"] = {}
        for sym in sorted(APPROVED_SYMBOLS):
            t = _trend_table_state().get(sym)
            if not t:
                result["trend_table_summary"][sym] = None
                continue

            buy_confirmation = _required_buy_confirmations(sym, result.get("account") or {})
            sell_confirmation = _required_sell_confirmations(sym, result.get("account") or {})

            result["trend_table_summary"][sym] = {
                "direction": t.get("direction"),
                "strength": t.get("strength"),
                "consecutive_count": t.get("consecutive_count"),
                "last_signal": t.get("last_signal"),
                "flip_event": t.get("flip_event"),
                "required_buy_confirmations": buy_confirmation.get("required_buy_confirmations"),
                "required_sell_confirmations": sell_confirmation.get("required_sell_confirmations"),
                "fast_lane_buy_flip": is_fast_lane_buy_flip(
                    t,
                    required_buy_confirmations=buy_confirmation.get("required_buy_confirmations") or 3,
                ),
                "fast_lane_sell_flip": is_fast_lane_sell_flip(
                    t,
                    required_sell_confirmations=sell_confirmation.get("required_sell_confirmations") or 2,
                ),
            }
    except Exception as e:
        logger.error(f"/status trend_table_summary error: {e}")

    # Market context
    try:
        result["market_bias"] = _market_bias_state().get(symbol)
    except Exception as e:
        result["market_bias_error"] = str(e)

    # Successful buys today
    try:
        result["successful_buys_today"] = _successful_buys_today(symbol)
        result["max_buys_per_symbol_per_day"] = MAX_BUYS_PER_SYMBOL_PER_DAY
        result["daily_symbol_buy_limit_hit"] = (
            result["successful_buys_today"] >= MAX_BUYS_PER_SYMBOL_PER_DAY
        )
    except Exception as e:
        result["successful_buys_today_error"] = str(e)

    # Cooldowns
    try:
        cooldowns = {}
        for action in ("buy", "sell"):
            last = _read_cooldown(symbol, action)
            if last:
                elapsed = (now_et_value - last).total_seconds()
                active = elapsed < 15 * 60
                cooldowns[action] = {
                    "last_order_time": last.isoformat(),
                    "active": active,
                    "minutes_remaining": int((15 * 60 - elapsed) // 60) if active else 0,
                }
            else:
                cooldowns[action] = None
        result["cooldowns"] = cooldowns
    except Exception as e:
        result["cooldown_error"] = str(e)

    # Recent sell / churn
    try:
        last_sell = _read_recent_sell(symbol)
        if last_sell:
            ts, sell_price = last_sell
            elapsed = (now_et_value - ts).total_seconds()
            result["recent_sell"] = {
                "last_sell_time": ts.isoformat(),
                "last_sell_price": sell_price,
                "within_30min_churn_window": elapsed < 30 * 60,
                "minutes_remaining": int((30 * 60 - elapsed) // 60) if elapsed < 30 * 60 else 0,
            }
        else:
            result["recent_sell"] = None
    except Exception as e:
        result["recent_sell_error"] = str(e)

    # Cluster exposure
    try:
        balance = float(state.get("balance") or 0)
        result["correlation_exposure"] = _cluster_exposure(symbol, balance)
    except Exception as e:
        result["correlation_exposure_error"] = str(e)

    # Macro risk
    try:
        result["macro_risk"] = get_macro_risk(Path(__file__).parent)
    except Exception as e:
        result["macro_risk_error"] = str(e)

    # Observe-only rolling multi-day momentum context
    try:
        result["rolling_momentum"] = rolling_symbol_context(symbol)
    except Exception as e:
        result["rolling_momentum_error"] = str(e)

    # Observe-only market alignment
    try:
        service = globals().get("_trend_state_service")
        result["market_alignment"] = (
            service.symbol_market_alignment(symbol)
            if service is not None
            else _symbol_market_alignment(symbol)
        )
    except Exception as e:
        result["market_alignment_error"] = str(e)

    # Observe-only daily prediction intelligence
    try:
        result["symbol_intelligence"] = _symbol_intelligence_for_symbol(symbol)
    except Exception as e:
        result["symbol_intelligence_error"] = str(e)

    # Observe-only adaptive BUY confirmation diagnostics
    try:
        result["adaptive_buy_confirmation"] = _required_buy_confirmations(symbol, result)
    except Exception as e:
        result["adaptive_buy_confirmation_error"] = str(e)

    # High-level buy block reasons
    buy_blocks = []

    override_service = globals().get("_symbol_override_service")
    override_reason = (
        override_service.block_reason(symbol, "buy")
        if override_service is not None
        else _symbol_override_block(symbol, "buy")
    )
    if override_reason:
        buy_blocks.append("symbol_override")

    if not market_hours_open:
        buy_blocks.append("market_hours")

    acct = result.get("account") or {}
    if acct.get("circuit_breaker_active_for_buys"):
        buy_blocks.append("circuit_breaker")

    trend = result.get("trend") or {}
    prediction_gate = (state or {}).get("prediction_gate") or {}

    if prediction_gate.get("prediction_decision") == "block":
        buy_blocks.append(
            f"prediction_gate:{prediction_gate.get('prediction_score')}:{prediction_gate.get('prediction_reason')}"
    )
    bias = result.get("market_bias") or {}

    if bias.get("bias") == "avoid":
        buy_blocks.append("market_bias_avoid")

    fundamental_score = bias.get("fundamental_score")

    if fundamental_score in ("bearish", "strong_bearish"):
        buy_blocks.append("fundamental_score")

    if bias.get("entry_quality") in ("do_not_chase", "avoid_chasing"):
        buy_blocks.append("chase_prevention")

    if result.get("daily_symbol_buy_limit_hit"):
        buy_blocks.append("daily_symbol_buy_limit")

    macro = result.get("macro_risk") or {}
    if macro.get("block_new_buys"):
        buy_blocks.append("macro_risk")

    for c in result.get("correlation_exposure") or []:
        if c.get("limit_hit"):
            buy_blocks.append(f"correlation_cap:{c.get('cluster')}")

    result["would_block_buy_because"] = buy_blocks
    result["buy_would_pass_known_prechecks"] = len(buy_blocks) == 0

    return result, 200
