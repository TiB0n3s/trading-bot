"""Runtime-bound payload builder extracted from app.py.

This is an interim boundary: route code calls this service while the service
resolves runtime dependencies from the Flask composition module.
"""

from __future__ import annotations


def _bind_runtime(runtime):
    globals().update(
        {name: value for name, value in vars(runtime).items() if not name.startswith("__")}
    )


def _trend_table_state():
    service = globals().get("_trend_state_service")
    return getattr(service, "trend_table", globals().get("_trend_table", {}))


def _market_bias_state():
    service = globals().get("_market_context_service")
    return getattr(service, "market_bias", globals().get("_market_bias", {}))


def _market_context_summary():
    service = globals().get("_market_context_service")
    if service is not None:
        service.load()
        return service.file_summary()

    _load_market_context()
    ctx_path = Path(__file__).parent / "market_context.json"
    if ctx_path.exists():
        ctx = json.loads(ctx_path.read_text())
        return ctx.get("market_date"), ctx.get("macro_sentiment")
    return None, None


def build_positions_payload(runtime):
    _bind_runtime(runtime)
    result = {"timestamp": datetime.now().isoformat()}

    balance = 0.0
    daily_pnl_pct = None
    try:
        state = get_mock_account_state()
        balance = float(state.get("balance") or 0)
        daily_pnl_pct = state.get("daily_pnl_pct")
    except Exception as e:
        logger.error(f"/positions account state error: {e}")

    def _cooldown_active(symbol):
        try:
            now_et_value = now_et()
            market_hours_open = is_market_hours(now_et_value)
            for (sym, _action), ts in _last_order.items():
                if sym == symbol and (now_et_value - ts).total_seconds() < 15 * 60:
                    return True
        except Exception:
            pass
        return False

    positions_list = []
    total_unrealized = 0.0
    try:
        for p in broker_service.list_positions():
            try:
                qty = float(p.qty)
                avg_entry = float(p.avg_entry_price)
                current = float(p.current_price)
                market_value = float(p.market_value)
                unrealized_pl = float(p.unrealized_pl)
                unrealized_pl_pct = float(p.unrealized_plpc) * 100
                exposure_pct = (market_value / balance * 100) if balance else None
                trend = _trend_table_state().get(p.symbol) or {}
                bias_entry = _market_bias_state().get(p.symbol) or {}
                entry_ctx = _open_entry_context(p.symbol) or {}

                positions_list.append(
                    {
                        "symbol": p.symbol,
                        "qty": qty,
                        "avg_entry_price": round(avg_entry, 4),
                        "current_price": round(current, 4),
                        "market_value": round(market_value, 2),
                        "unrealized_pl": round(unrealized_pl, 2),
                        "unrealized_pl_pct": round(unrealized_pl_pct, 3),
                        "unrealized_plpc": round(unrealized_pl_pct, 3),
                        "exposure_pct": round(exposure_pct, 2)
                        if exposure_pct is not None
                        else None,
                        "exposure_cap_hit": bool(exposure_pct is not None and exposure_pct >= 4.0),
                        "trend_direction": trend.get("direction"),
                        "trend_strength": trend.get("strength"),
                        "market_bias": bias_entry.get("bias"),
                        "cooldown_active": _cooldown_active(p.symbol),
                        # Entry-side context from the oldest currently-open FIFO lot.
                        "entry_timestamp": entry_ctx.get("entry_timestamp"),
                        "open_lot_qty": entry_ctx.get("open_lot_qty"),
                        "entry_fill_price": entry_ctx.get("entry_fill_price"),
                        "entry_signal_price": entry_ctx.get("entry_signal_price"),
                        "holding_minutes": entry_ctx.get("holding_minutes"),
                        "entry_market_bias": entry_ctx.get("entry_market_bias"),
                        "entry_risk_level": entry_ctx.get("entry_risk_level"),
                        "entry_quality": entry_ctx.get("entry_quality"),
                        "entry_trend_direction": entry_ctx.get("entry_trend_direction"),
                        "entry_trend_strength": entry_ctx.get("entry_trend_strength"),
                        "entry_momentum_direction": entry_ctx.get("entry_momentum_direction"),
                        "entry_momentum_pct": entry_ctx.get("entry_momentum_pct"),
                        "entry_macro_regime": entry_ctx.get("entry_macro_regime"),
                        "entry_risk_multiplier": entry_ctx.get("entry_risk_multiplier"),
                        "entry_correlation_cluster": entry_ctx.get("entry_correlation_cluster"),
                        "entry_cluster_exposure_pct": entry_ctx.get("entry_cluster_exposure_pct"),
                    }
                )
                total_unrealized += unrealized_pl
            except Exception as e:
                logger.warning(f"/positions per-symbol error for {p.symbol}: {e}")
    except Exception as e:
        logger.error(f"/positions list_positions error: {e}")

    market_context_date = None
    macro_sentiment = None
    try:
        market_context_date, macro_sentiment = _market_context_summary()
    except Exception as e:
        logger.error(f"/positions market_context read error: {e}")

    result["summary"] = {
        "total_positions": len(positions_list),
        "max_positions": MAX_OPEN_POSITIONS,
        "total_unrealized_pl": round(total_unrealized, 2),
        "account_balance": balance,
        "daily_pnl_pct": daily_pnl_pct,
        "market_context_date": market_context_date,
        "macro_sentiment": macro_sentiment,
    }
    result["positions"] = sorted(positions_list, key=lambda x: -(x.get("market_value") or 0))
    try:
        for position in result.get("positions", []):
            symbol = position.get("symbol")
            position["intelligence"] = get_position_intelligence(symbol)
    except Exception as e:
        result["position_intelligence_error"] = str(e)

    return result
