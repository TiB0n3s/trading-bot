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


def build_health_payload(runtime):
    _bind_runtime(runtime)
    account = broker_service.get_account()
    return {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "account": account,
    }


def _market_session():
    return market_session()


def _session_momentum_summary():
    try:
        return context_repo.session_momentum_summary()
    except Exception as exc:
        logger.warning(f"session momentum summary unavailable: {exc}")
        return {}


def _session_momentum_snapshot(limit=40):
    try:
        return context_repo.session_momentum_snapshot(limit=limit)
    except Exception as exc:
        logger.warning(f"session momentum snapshot unavailable: {exc}")
        return []


def _latest_session_momentum_for_symbol(symbol):
    try:
        row = get_latest_session_momentum(symbol)
        return dict(row) if row else None
    except Exception as exc:
        logger.warning(f"session momentum unavailable for {symbol}: {exc}")
        return None


def _symbol_intelligence_snapshot(market_date=None):
    market_date = market_date or expected_market_context_date().isoformat()
    try:
        rows = context_repo.symbol_intelligence_rows(market_date)
        symbols = {}
        for row in rows:
            item = dict(row)
            symbol = item.pop("symbol")
            item["prediction_confidence"] = item.pop("confidence", None)
            item["prediction_reason"] = item.pop("reason", None)
            item["prediction_decision"] = "observe_only"
            symbols[symbol] = item

        return {
            "available": bool(symbols),
            "market_date": market_date,
            "symbol_count": len(symbols),
            "observe_only": True,
            "symbols": symbols,
        }
    except Exception as exc:
        logger.warning(f"symbol intelligence unavailable: {exc}")
        return {
            "available": False,
            "market_date": market_date,
            "observe_only": True,
            "error": str(exc),
            "symbols": {},
            "symbol_count": 0,
        }


def symbol_intelligence_for_symbol(runtime, symbol, market_date=None):
    _bind_runtime(runtime)
    snapshot = _symbol_intelligence_snapshot(market_date=market_date)
    return (snapshot.get("symbols") or {}).get(symbol.upper())


def build_status_payload(runtime):
    _bind_runtime(runtime)
    result = {
        "timestamp": datetime.now().isoformat(),
        "execution_mode": EXECUTION_MODE,
        "runtime_config": public_runtime_config(),
    }
    result["session_momentum_gate_enabled"] = ENFORCE_SESSION_MOMENTUM_GATE
    result["prediction_gate_mode"] = PREDICTION_GATE_MODE
    result["prediction_gate_thresholds"] = PREDICTION_GATE_THRESHOLDS
    result["prediction_gate_name"] = "deterministic_signal_quality_gate"
    result["ml_prediction_cache"] = prediction_cache_status()
    result["decision_policy"] = public_decision_policy_config()
    result["policy_controls"] = public_policy_control_config()
    result["runtime_metrics"] = metrics_snapshot()
    result["strategy_engine_mode"] = STRATEGY_ENGINE_MODE
    result["execution_policy_mode"] = os.getenv("EXECUTION_POLICY_MODE", "compare").strip().lower()
    result["intra_session_tape_degradation_enabled"] = INTRA_SESSION_TAPE_DEGRADATION_ENABLED
    result["one_bar_confirmation_hold_enabled"] = ONE_BAR_CONFIRMATION_HOLD_ENABLED
    result["prediction_soft_avoid_min_sample_size"] = PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE
    result["macro_position_count_floor"] = MACRO_POSITION_COUNT_FLOOR
    result["tape_exception_enabled"] = TAPE_EXCEPTION_ENABLED
    result["open_momentum_fast_lane_enabled"] = OPEN_MOMENTUM_FAST_LANE_ENABLED
    result["risk_policy_mode"] = RISK_POLICY_MODE
    result["portfolio_rotation"] = {
        "mode": os.getenv("PORTFOLIO_REPLACEMENT_MODE", "observe_only").strip().lower(),
        "live_sells": os.getenv("PORTFOLIO_REPLACEMENT_LIVE_SELLS", "false").strip().lower()
        in ("1", "true", "yes", "on"),
        "require_replace_now": os.getenv(
            "PORTFOLIO_REPLACEMENT_REQUIRE_REPLACE_NOW", "true"
        ).strip().lower() in ("1", "true", "yes", "on"),
        "min_candidate_score": float(os.getenv("PORTFOLIO_REPLACEMENT_MIN_CANDIDATE_SCORE", "120")),
        "min_buy_score": float(os.getenv("PORTFOLIO_REPLACEMENT_MIN_BUY_SCORE", "15")),
        "weak_holding_plpc": float(os.getenv("PORTFOLIO_REPLACEMENT_WEAK_HOLDING_PLPC", "-1.00")),
        "runtime_effect": "live_sell_path" if os.getenv(
            "PORTFOLIO_REPLACEMENT_LIVE_SELLS", "false"
        ).strip().lower() in ("1", "true", "yes", "on") else "observe_only",
    }
    result["alerts"] = alert_config_public()
    result["session_momentum_summary"] = _session_momentum_summary()
    result["session_momentum"] = _session_momentum_snapshot()
    result["symbol_intelligence"] = _symbol_intelligence_snapshot()
    result["policy_artifacts"] = policy_artifact_status(Path(__file__).parent)
    
    # Uptime
    try:
        elapsed = datetime.now(timezone.utc) - _START_TIME
        h, rem = divmod(int(elapsed.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        result["uptime"] = f"{h}h {m}m {s}s"
    except Exception:
        pass

    # Market session
    try:
        result["market_session"] = _market_session()
    except Exception:
        pass

    # Macro risk regime
    try:
        result["macro_risk"] = get_macro_risk(Path(__file__).parent)
    except Exception as e:
        logger.error(f"/status macro_risk error: {e}")

    # Observe-only rolling multi-day momentum context
    try:
        result["rolling_momentum"] = rolling_summary()
    except Exception as e:
        logger.error(f"/status rolling_momentum error: {e}")

    # Account summary + daily P&L (via get_mock_account_state)
    try:
        state = get_mock_account_state()
        balance = state.get("balance", 0)
        result["account"] = {
            "balance":         balance,
            "portfolio_value": state.get("portfolio_value"),
            "daily_pnl":       state.get("daily_pnl"),
            "daily_pnl_pct":   state.get("daily_pnl_pct"),
            "circuit_breaker_triggered": (state.get("daily_pnl_pct") or 0) <= -3.0,
        }
    except Exception as e:
        logger.error(f"/status account error: {e}")
        balance = 0

    # Buying power (broker account has it; get_mock_account_state does not)
    try:
        acct = broker_service.get_account()
        if acct and "account" in result:
            result["account"]["buying_power"] = acct["buying_power"]
    except Exception:
        pass

    # Read-only ledger/DB summary.
    try:
        result["ledger_summary"] = ledger_summary()
    except Exception as e:
        result["ledger_summary_error"] = str(e)

    # Detailed positions (now with trend, market_bias, and exposure-cap signals)
    symbols_at_cap = []
    try:
        alpaca_positions = broker_service.list_positions()
        pos_list = []
        for p in sorted(alpaca_positions, key=lambda x: -float(x.market_value)):
            try:
                mv = float(p.market_value)
                pct_of_balance = round(mv / balance * 100, 2) if balance else None
                cap_hit = bool(pct_of_balance is not None and pct_of_balance >= 4.0)
                if cap_hit:
                    symbols_at_cap.append(p.symbol)
                trend = _trend_table_state().get(p.symbol) or {}
                bias_entry = _market_bias_state().get(p.symbol) or {}
                pos_list.append({
                    "symbol":          p.symbol,
                    "qty":             float(p.qty),
                    "current_price":   float(p.current_price),
                    "value":           mv,
                    "unrealized_pl":   float(p.unrealized_pl),
                    "pct_of_balance":  pct_of_balance,
                    "trend_direction": trend.get("direction"),
                    "trend_strength":  trend.get("strength"),
                    "market_bias":     bias_entry.get("bias"),
                    "session_momentum": _latest_session_momentum_for_symbol(p.symbol),
                    "exposure_cap_hit": cap_hit,
                })
            except Exception as e:
                logger.warning(f"/status per-symbol error for {p.symbol}: {e}")
        result["positions"] = pos_list
        result["position_count"] = f"{len(alpaca_positions)}/8"
    except Exception as e:
        logger.error(f"/status positions error: {e}")

    # Correlation exposure per cluster (mega_cap_tech / broad_index / energy)
    try:
        cluster_status = {}
        for cluster_name, members in CORRELATION_CLUSTERS.items():
            value = 0.0
            held = []
            for p in broker_service.list_positions():
                if p.symbol in members:
                    mv = float(p.market_value)
                    value += mv
                    held.append({
                        "symbol": p.symbol,
                        "value": round(mv, 2),
                    })

            exposure_pct = round(value / balance * 100, 2) if balance else None
            limit_pct = CLUSTER_EXPOSURE_LIMITS.get(cluster_name)
            cluster_status[cluster_name] = {
                "members": sorted(members),
                "held": sorted(held, key=lambda x: -x["value"]),
                "value": round(value, 2),
                "exposure_pct": exposure_pct,
                "limit_pct": limit_pct,
                "limit_hit": bool(
                    exposure_pct is not None and limit_pct is not None and exposure_pct >= limit_pct
                ),
            }

        result["correlation_exposure"] = cluster_status
    except Exception as e:
        logger.error(f"/status correlation_exposure error: {e}")

    # Read-only risk package telemetry.
    # This does not replace or weaken live inline risk gates.
    if RISK_POLICY_MODE == "compare":
        try:
            macro_live = result.get("macro_risk") or get_macro_risk(Path(__file__).parent)
            positions_for_risk = result.get("positions") or []
            account_for_risk = result.get("account") or {}

            result["risk_account_snapshot"] = account_risk_snapshot(
                account=account_for_risk,
                positions=positions_for_risk,
                daily_pnl_pct=account_for_risk.get("daily_pnl_pct"),
                max_positions=int(macro_live.get("max_new_positions") or 8),
            )

            guard_policy = live_guard_policy(os.environ)
            allowed, guard_reason = live_order_allowed(guard_policy)
            result["risk_live_guard_policy"] = {
                **guard_policy,
                "live_order_allowed": allowed,
                "live_order_reason": guard_reason,
            }

            ctx_path = Path(__file__).parent / "market_context.json"
            if ctx_path.exists():
                ctx = json.loads(ctx_path.read_text())
                macro_policy_compare = policy_from_market_context(ctx)
                result["risk_macro_policy_compare"] = {
                    "package_policy": macro_policy_compare,
                    "live_macro_risk": macro_live,
                    "matches_live": (
                        macro_policy_compare.get("macro_regime") == macro_live.get("macro_regime")
                        and macro_policy_compare.get("risk_multiplier") == macro_live.get("risk_multiplier")
                        and macro_policy_compare.get("max_new_positions") == macro_live.get("max_new_positions")
                        and macro_policy_compare.get("block_new_buys") == macro_live.get("block_new_buys")
                    ),
                }
            else:
                result["risk_macro_policy_compare"] = {
                    "error": "market_context.json missing",
                    "live_macro_risk": macro_live,
                }
        except Exception as e:
            result["risk_policy_error"] = str(e)

    # Pre-check state — what would block / pass right now if a buy signal arrived
    try:
        now_et_value = now_et()
        market_hours_open = is_market_hours(now_et_value)

        # Stage B: read cooldowns and recent_sells from DB tables so the
        # snapshot reflects state across all gunicorn workers (the in-memory
        # dicts only hold this worker's view).
        et = pytz.timezone("America/New_York")
        cooldowns = []
        churn = []
        try:
            cd_rows = cooldown_repo.cooldown_rows()
            cs_rows = cooldown_repo.recent_sell_rows()
            for sym, act, ts_str in cd_rows:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = et.localize(ts)
                    elapsed = (now_et_value - ts).total_seconds()
                    if elapsed < 15 * 60:
                        cooldowns.append({
                            "symbol": sym,
                            "action": act,
                            "minutes_remaining": int((15 * 60 - elapsed) // 60),
                        })
                except Exception:
                    pass
            for sym, ts_str, *_ in cs_rows:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = et.localize(ts)
                    elapsed = (now_et_value - ts).total_seconds()
                    if elapsed < 30 * 60:
                        churn.append(sym)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"/status DB read for pre_check_state failed: {e}")

        trend_blocked = [
            {"symbol": sym, "direction": t.get("direction"), "strength": t.get("strength")}
            for sym, t in _trend_table_state().items()
            if sym in APPROVED_SYMBOLS and t.get("direction") in ("neutral", "bearish")
        ]

        bias_avoid = sorted(
            sym for sym, entry in _market_bias_state().items()
            if (entry or {}).get("bias") == "avoid"
        )

        daily_pnl_pct = result.get("account", {}).get("daily_pnl_pct")
        result["pre_check_state"] = {
            "market_hours_open": market_hours_open,
            "circuit_breaker_active": (daily_pnl_pct or 0) < DAILY_LOSS_LIMIT_PCT,
            "symbols_on_cooldown": sorted(cooldowns, key=lambda c: (c["symbol"], c["action"])),
            "symbols_on_churn_block": sorted(churn),
            "symbols_at_exposure_cap": sorted(symbols_at_cap),
            "trend_gate_blocked": sorted(trend_blocked, key=lambda x: x["symbol"]),
            "market_bias_avoided": bias_avoid,
        }
    except Exception as e:
        logger.error(f"/status pre_check_state error: {e}")

    # Trend snapshot for all 15 approved symbols (not just held positions)
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

    # Today's signal counts from trades.db
    try:
        result["today_signals"] = trades_repo.today_signal_counts()
    except Exception as e:
        logger.error(f"/status signal counts error: {e}")

    try:
        result["intelligence"] = get_intelligence_snapshot()
    except Exception as e:
        result["intelligence"] = {
            "available": False,
            "error": str(e),
        }

    return result
