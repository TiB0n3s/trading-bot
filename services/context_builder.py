"""Context-building stage interfaces and context extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from services.downside_asymmetry_service import evaluate_downside_asymmetry
from services.exit_decision_quality_service import evaluate_exit_decision_quality
from services.market_microstructure_service import classify_market_microstructure
from services.market_participation_service import evaluate_market_participation
from services.market_regime_service import classify_market_regime
from services.execution_quality_service import estimate_execution_quality
from services.portfolio_decision_service import evaluate_portfolio_decision
from services.signal_models import DecisionContext, SignalContext, SignalRuntimeState
from services.setup_context_service import (
    SetupContextDeps,
    build_setup_observation,
    get_recent_favorable_setup,
    remember_favorable_setup,
)
from services.volatility_normalization_service import classify_volatility_normalization


@dataclass(frozen=True)
class SetupObservation:
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PredictionObservation:
    data: dict[str, Any] = field(default_factory=dict)
    score: float | None = None
    bucket: str = "unknown"
    sample_size: int = 0
    confidence: str | None = None
    decision: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class SessionMomentumObservation:
    data: dict[str, Any] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)
    label: str | None = None
    score: float | None = None
    severity: str | None = None
    would_block: bool = False
    size_hint: str | None = None


@dataclass(frozen=True)
class StrategyObservation:
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketAlignmentObservation:
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketRegimeObservation:
    data: dict[str, Any] = field(default_factory=dict)
    composite_regime: str | None = None
    trend_regime: str | None = None
    volatility_regime: str | None = None
    confidence: str | None = None
    strategy_weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketMicrostructureObservation:
    data: dict[str, Any] = field(default_factory=dict)
    session_phase: str | None = None
    breakout_quality: str | None = None
    liquidity_state: str | None = None
    reversion_risk: str | None = None
    expectancy_modifier: float = 1.0


@dataclass(frozen=True)
class MarketParticipationObservation:
    data: dict[str, Any] = field(default_factory=dict)
    participation_state: str | None = None
    confirmation_score: float = 0.0
    isolated_move_risk: str | None = None
    expectancy_modifier: float = 1.0


@dataclass(frozen=True)
class VolatilityNormalizationObservation:
    data: dict[str, Any] = field(default_factory=dict)
    stretch_state: str | None = None
    chase_risk: str | None = None
    volatility_adjusted_score: float = 0.0
    expectancy_modifier: float = 1.0


@dataclass(frozen=True)
class DownsideAsymmetryObservation:
    data: dict[str, Any] = field(default_factory=dict)
    downside_state: str | None = None
    downside_score: float = 0.0
    expected_adverse_modifier: float = 1.0


@dataclass(frozen=True)
class ExitDecisionQualityObservation:
    data: dict[str, Any] = field(default_factory=dict)
    exit_pressure_state: str | None = None
    exit_quality_score: float = 0.0
    recommended_action: str | None = None


@dataclass(frozen=True)
class PortfolioObservation:
    data: dict[str, Any] = field(default_factory=dict)
    decision: str | None = None
    size_multiplier: float = 1.0
    duplicate_risk_score: float = 0.0


@dataclass(frozen=True)
class ExecutionQualityObservation:
    data: dict[str, Any] = field(default_factory=dict)
    decision: str | None = None
    fill_quality: str | None = None
    net_execution_cost_pct: float = 0.0


@dataclass(frozen=True)
class TrendObservation:
    data: dict[str, Any] = field(default_factory=dict)
    direction: str | None = None
    strength: str | None = None
    consecutive_count: int = 0
    last_signal: str | None = None
    confirmation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpportunityObservation:
    data: dict[str, Any] = field(default_factory=dict)
    score: float | None = None
    bucket: str | None = None
    recommendation: str | None = None
    reasons: list[Any] = field(default_factory=list)
    cap: float | None = None


@dataclass(frozen=True)
class BuiltSignalContext:
    account_state: dict[str, Any]
    decision_context: dict[str, Any]
    setup: SetupObservation
    prediction: PredictionObservation
    session: SessionMomentumObservation
    trend: TrendObservation
    strategy: StrategyObservation
    market_alignment: MarketAlignmentObservation
    market_regime: MarketRegimeObservation
    market_microstructure: MarketMicrostructureObservation
    market_participation: MarketParticipationObservation
    volatility_normalization: VolatilityNormalizationObservation
    downside_asymmetry: DownsideAsymmetryObservation
    exit_decision_quality: ExitDecisionQualityObservation
    portfolio: PortfolioObservation
    execution_quality: ExecutionQualityObservation
    opportunity: OpportunityObservation
    claude_account_state: dict[str, Any]
    summary: dict[str, Any]


@dataclass(frozen=True)
class ContextAssemblyDeps:
    """Runtime dependencies for signal context assembly.

    This keeps context ownership in the service layer while allowing the live
    path to pass existing functions during migration.
    """

    execution_mode: str
    market_bias: dict[str, dict[str, Any]]
    trend_table: dict[str, dict[str, Any]]
    rolling_symbol_context: Callable[[str], dict[str, Any] | None]
    prior_session_context: Callable[[str], dict[str, Any] | None]
    build_tape_context: Callable[..., dict[str, Any]]
    get_momentum: Callable[..., dict[str, Any] | None]
    setup_context_deps: SetupContextDeps
    log: Any


class SignalContextRuntime:
    """Behavior-preserving context owner for the live signal path.

    The live processor still owns enforcement during the migration, but this
    runtime owns context assembly and keeps the latest BuiltSignalContext view.
    """

    def __init__(self, state: SignalRuntimeState, deps: ContextAssemblyDeps):
        self.state = state
        self.deps = deps
        self.built = build_initial_signal_context(state, deps)

    @property
    def account_state(self) -> dict[str, Any]:
        return self.state.account_state

    @property
    def setup(self) -> SetupObservation:
        return self.built.setup

    @property
    def trend(self) -> TrendObservation:
        return self.built.trend

    @property
    def session(self) -> SessionMomentumObservation:
        return self.built.session

    @property
    def prediction(self) -> PredictionObservation:
        return self.built.prediction

    @property
    def strategy(self) -> StrategyObservation:
        return self.built.strategy

    @property
    def opportunity(self) -> OpportunityObservation:
        return self.built.opportunity

    @property
    def market_alignment(self) -> MarketAlignmentObservation:
        return self.built.market_alignment

    @property
    def market_regime(self) -> MarketRegimeObservation:
        return self.built.market_regime

    @property
    def market_microstructure(self) -> MarketMicrostructureObservation:
        return self.built.market_microstructure

    @property
    def market_participation(self) -> MarketParticipationObservation:
        return self.built.market_participation

    @property
    def volatility_normalization(self) -> VolatilityNormalizationObservation:
        return self.built.volatility_normalization

    @property
    def downside_asymmetry(self) -> DownsideAsymmetryObservation:
        return self.built.downside_asymmetry

    @property
    def exit_decision_quality(self) -> ExitDecisionQualityObservation:
        return self.built.exit_decision_quality

    @property
    def portfolio(self) -> PortfolioObservation:
        return self.built.portfolio

    @property
    def execution_quality(self) -> ExecutionQualityObservation:
        return self.built.execution_quality

    def refresh(self, **kwargs: Any) -> BuiltSignalContext:
        self.built = build_final_signal_context(
            account_state=self.account_state,
            trend_table=self.deps.trend_table,
            **kwargs,
        )
        return self.built

    def hydrate_buy_live_context(self, *, only_missing: bool = False) -> BuiltSignalContext:
        hydrate_buy_live_context(self.state, self.deps, only_missing=only_missing)
        return self.refresh()

    def build_prediction_observation(
        self,
        *,
        trend: dict[str, Any],
        bias_entry: dict[str, Any],
        evaluate_signal_quality_gate: Callable[..., dict[str, Any]],
        get_cached_prediction: Callable[[str], dict[str, Any] | None],
        ml_prediction_bucket: Callable[[Any], str],
    ) -> PredictionObservation:
        observation = build_prediction_observation(
            symbol=self.state.symbol,
            account_state=self.account_state,
            trend=trend,
            bias_entry=bias_entry,
            evaluate_signal_quality_gate=evaluate_signal_quality_gate,
            get_cached_prediction=get_cached_prediction,
            ml_prediction_bucket=ml_prediction_bucket,
            log=self.deps.log,
        )
        self.refresh()
        return observation

    def build_session_momentum_observation(
        self,
        *,
        get_latest_session_momentum: Callable[[str], dict[str, Any] | None],
        session_momentum_is_fresh: Callable[[dict[str, Any]], bool],
    ) -> SessionMomentumObservation:
        observation = build_session_momentum_observation(
            symbol=self.state.symbol,
            account_state=self.account_state,
            get_latest_session_momentum=get_latest_session_momentum,
            session_momentum_is_fresh=session_momentum_is_fresh,
            log=self.deps.log,
        )
        self.refresh()
        return observation

    def build_buy_opportunity_observation(
        self,
        *,
        trend: dict[str, Any],
        bias_entry: dict[str, Any],
        evaluate_buy_opportunity: Callable[..., dict[str, Any]],
        required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        prediction_gate: dict[str, Any] | None = None,
        log_prefix: str = "BUY opportunity",
    ) -> OpportunityObservation:
        observation = build_buy_opportunity_observation(
            symbol=self.state.symbol,
            account_state=self.account_state,
            trend=trend,
            bias_entry=bias_entry,
            evaluate_buy_opportunity=evaluate_buy_opportunity,
            required_buy_confirmations=required_buy_confirmations,
            prediction_gate=prediction_gate,
            log_prefix=log_prefix,
            log=self.deps.log,
        )
        self.refresh()
        return observation

    def build_trend_confirmation_observation(
        self,
        *,
        current_et: datetime,
        required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        required_sell_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        is_fast_lane_buy_flip: Callable[..., bool],
        is_fast_lane_sell_flip: Callable[..., bool],
        market_open_minutes: int,
        open_momentum_fast_lane_enabled: bool,
        iex_thin_symbols: set[str],
    ) -> TrendObservation:
        observation = build_trend_confirmation_observation(
            symbol=self.state.symbol,
            action=self.state.action,
            account_state=self.account_state,
            trend_table=self.deps.trend_table,
            market_bias=self.deps.market_bias,
            current_et=current_et,
            required_buy_confirmations=required_buy_confirmations,
            required_sell_confirmations=required_sell_confirmations,
            is_fast_lane_buy_flip=is_fast_lane_buy_flip,
            is_fast_lane_sell_flip=is_fast_lane_sell_flip,
            market_open_minutes=market_open_minutes,
            open_momentum_fast_lane_enabled=open_momentum_fast_lane_enabled,
            iex_thin_symbols=iex_thin_symbols,
        )
        self.refresh()
        return observation

    def build_market_alignment_observation(
        self,
        *,
        symbol_market_alignment: Callable[[str], dict[str, Any]],
    ) -> MarketAlignmentObservation:
        observation = build_market_alignment_observation(
            symbol=self.state.symbol,
            action=self.state.action,
            account_state=self.account_state,
            symbol_market_alignment=symbol_market_alignment,
            log=self.deps.log,
        )
        self.refresh()
        return observation

    def hydrate_pre_macro_context(
        self,
        *,
        get_macro_risk: Callable[[Any], dict[str, Any]],
        base_dir: Any,
        evaluate_buy_opportunity: Callable[..., dict[str, Any]],
        required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    ) -> dict[str, Any]:
        macro_risk = hydrate_pre_macro_context(
            self,
            get_macro_risk=get_macro_risk,
            base_dir=base_dir,
            evaluate_buy_opportunity=evaluate_buy_opportunity,
            required_buy_confirmations=required_buy_confirmations,
        )
        self.refresh()
        return macro_risk

    def apply_market_bias_context(self, *, bias_entry: dict[str, Any]) -> None:
        apply_market_bias_context(
            action=self.state.action,
            account_state=self.account_state,
            bias_entry=bias_entry,
        )
        self.refresh()

    def hydrate_session_context(
        self,
        *,
        get_latest_session_momentum: Callable[[str], dict[str, Any] | None],
        session_momentum_is_fresh: Callable[[dict[str, Any]], bool],
    ) -> None:
        self.build_session_momentum_observation(
            get_latest_session_momentum=get_latest_session_momentum,
            session_momentum_is_fresh=session_momentum_is_fresh,
        )

    def hydrate_buy_momentum_context(self) -> None:
        hydrate_buy_momentum_context(self)
        self.refresh()

    def hydrate_strategy_context(
        self,
        *,
        strategy_engine_mode: str,
        evaluate_strategy_observe_only: Callable[..., Any],
        symbol_market_alignment: Callable[[str], dict[str, Any]],
        apply_size_cap: Callable[..., Any],
        env_float: Callable[[str, float], float],
    ) -> None:
        hydrate_strategy_context(
            self,
            strategy_engine_mode=strategy_engine_mode,
            evaluate_strategy_observe_only=evaluate_strategy_observe_only,
            symbol_market_alignment=symbol_market_alignment,
            apply_size_cap=apply_size_cap,
            env_float=env_float,
        )
        self.refresh()


def build_signal_context_runtime(
    state: SignalRuntimeState,
    deps: ContextAssemblyDeps,
) -> SignalContextRuntime:
    return SignalContextRuntime(state, deps)


def _latest_tape_bar_age_seconds(tape_state: dict[str, Any]) -> float | None:
    latest_raw = tape_state.get("latest_bar_timestamp")
    if not latest_raw:
        return None
    try:
        latest_ts = datetime.fromisoformat(str(latest_raw).replace("Z", "+00:00"))
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
        return round(
            (datetime.now(timezone.utc) - latest_ts.astimezone(timezone.utc)).total_seconds(),
            3,
        )
    except Exception:
        return None


def hydrate_buy_live_context(
    state: SignalRuntimeState,
    deps: ContextAssemblyDeps,
    *,
    only_missing: bool = False,
) -> None:
    if state.action != "buy":
        return

    symbol = state.symbol
    price = state.raw_signal.get("price")
    account_state = state.account_state
    premarket_bias = (deps.market_bias.get(symbol) or {}).get("bias")

    if not only_missing or "prior_session" not in account_state:
        try:
            prior_session = deps.prior_session_context(symbol)
            if prior_session:
                account_state["prior_session"] = prior_session
        except Exception as exc:
            deps.log.warning(f"prior_session context unavailable for {symbol}: {exc}")

    if not only_missing or "tape" not in account_state:
        try:
            tape_ctx = deps.build_tape_context(symbol, current_price=price)
            classification = tape_ctx.get("classification") or {}
            tape_state = tape_ctx.get("state") or {}
            account_state["tape"] = {
                **classification,
                "ok": tape_ctx.get("ok"),
                "bar_count": tape_ctx.get("bar_count"),
                "tape_bar_age_seconds": _latest_tape_bar_age_seconds(tape_state),
            }
        except Exception as exc:
            deps.log.warning(f"fresh tape context unavailable for {symbol}: {exc}")

    if not only_missing or "momentum" not in account_state:
        momentum = deps.get_momentum(symbol, price, premarket_bias=premarket_bias)
        if momentum:
            account_state["momentum"] = momentum
            account_state["premarket_alignment_source"] = (
                "live_tape" if premarket_bias is not None else "missing_bias"
            )


def build_initial_signal_context(
    state: SignalRuntimeState,
    deps: ContextAssemblyDeps,
) -> BuiltSignalContext:
    """Populate the first context slice needed by policy gates.

    This is intentionally behavior-preserving: it mutates state.account_state in
    the same shape the live signal flow expects, then returns a typed BuiltSignalContext
    for downstream migration.
    """

    symbol = state.symbol
    action = state.action
    account_state = state.account_state
    account_state.setdefault("symbol", symbol)
    account_state.setdefault("action", action)

    try:
        rolling_ctx = deps.rolling_symbol_context(symbol)
        if rolling_ctx:
            account_state["rolling_momentum"] = rolling_ctx
    except Exception as exc:
        deps.log.warning(f"rolling_momentum context unavailable for {symbol}: {exc}")

    account_state["execution_mode"] = deps.execution_mode
    hydrate_buy_live_context(state, deps)

    setup_obs = build_setup_observation(
        symbol,
        action,
        state.raw_signal.get("price"),
        account_state,
        deps.setup_context_deps,
    )
    account_state["setup_observation"] = setup_obs

    if action == "buy":
        remember_favorable_setup(symbol, setup_obs, deps.setup_context_deps)
        recent_favorable_setup = get_recent_favorable_setup(symbol, deps.setup_context_deps)
        if recent_favorable_setup:
            account_state["recent_favorable_setup"] = {
                "setup_label": recent_favorable_setup.get("setup_label"),
                "setup_policy_action": recent_favorable_setup.get("setup_policy_action"),
                "age_minutes": recent_favorable_setup.get("age_minutes"),
            }

    return build_final_signal_context(
        account_state=account_state,
        trend_table=deps.trend_table,
    )


def build_claude_account_state(account_state: dict[str, Any]) -> dict[str, Any]:
    claude_account_state = dict(account_state)
    adaptive_confirmation = account_state.get("adaptive_buy_confirmation") or {}
    market_alignment = account_state.get("market_alignment") or {}
    claude_account_state.pop("adaptive_buy_confirmation", None)
    claude_account_state.pop("adaptive_buy_confirmation_error", None)
    claude_account_state.pop("market_alignment", None)
    claude_account_state.pop("market_alignment_error", None)
    claude_account_state["market_context_summary"] = {
        "required_confirmations": adaptive_confirmation.get("required_buy_confirmations"),
        "confirmation_reasons": adaptive_confirmation.get("reasons"),
        "market_aligned": market_alignment.get("aligned_for_buy"),
        "alignment_reason": market_alignment.get("reason"),
    }
    return claude_account_state


def build_prediction_observation(
    *,
    symbol: str,
    account_state: dict[str, Any],
    trend: dict[str, Any],
    bias_entry: dict[str, Any],
    evaluate_signal_quality_gate: Callable[..., dict[str, Any]],
    get_cached_prediction: Callable[[str], dict[str, Any] | None],
    ml_prediction_bucket: Callable[[Any], str],
    log: Any,
) -> PredictionObservation:
    setup_obs = account_state.get("setup_observation") or {}
    momentum = account_state.get("momentum") or {}
    recent_favorable_setup = account_state.get("recent_favorable_setup")
    ml_prediction = get_cached_prediction(symbol)

    prediction_gate = evaluate_signal_quality_gate(
        trend_direction=trend.get("direction"),
        trend_strength=trend.get("strength"),
        market_bias=bias_entry.get("bias"),
        setup_label=setup_obs.get("setup_label"),
        setup_policy_action=setup_obs.get("setup_policy_action"),
        momentum_direction=momentum.get("direction"),
        momentum_pct=momentum.get("momentum_pct"),
        consecutive_buy_count=trend.get("consecutive_count") or 0,
        recent_favorable_setup=recent_favorable_setup,
        ml_prediction=ml_prediction,
    )

    account_state["prediction_gate"] = prediction_gate
    account_state["ml_prediction"] = ml_prediction or {}
    prediction_gate["ml_prediction_bucket"] = ml_prediction_bucket(
        prediction_gate.get("ml_prediction_score")
    )

    log.info(
        f"Signal quality gate for {symbol} BUY: "
        f"score={prediction_gate.get('prediction_score')} "
        f"decision={prediction_gate.get('prediction_decision')} "
        f"reason={prediction_gate.get('prediction_reason')} "
        f"ml_score={prediction_gate.get('ml_prediction_score')} "
        f"ml_compare={prediction_gate.get('ml_prediction_compare_decision')} "
        f"ml_agrees={prediction_gate.get('ml_prediction_agrees_with_gate')}"
    )

    return _prediction_observation(prediction_gate)


def build_session_momentum_observation(
    *,
    symbol: str,
    account_state: dict[str, Any],
    get_latest_session_momentum: Callable[[str], dict[str, Any] | None],
    session_momentum_is_fresh: Callable[[dict[str, Any]], bool],
    log: Any,
) -> SessionMomentumObservation:
    try:
        session_momentum = get_latest_session_momentum(symbol)

        if session_momentum and session_momentum_is_fresh(session_momentum):
            account_state["session_momentum"] = session_momentum
            log.info(
                f"Session momentum for {symbol}: "
                f"label={session_momentum.get('trend_label')} "
                f"score={session_momentum.get('trend_score')} "
                f"session_return={session_momentum.get('session_return_pct')} "
                f"5m={session_momentum.get('momentum_5m_pct')} "
                f"15m={session_momentum.get('momentum_15m_pct')} "
                f"30m={session_momentum.get('momentum_30m_pct')} "
                f"vwap_dist={session_momentum.get('distance_from_vwap_pct')}"
            )
        else:
            account_state["session_momentum"] = {
                "trend_label": "insufficient_data",
                "trend_score": 0,
                "reason": "missing or stale session momentum",
            }
            log.info(
                f"Session momentum unavailable/stale for {symbol}; using insufficient_data"
            )
    except Exception as exc:
        account_state["session_momentum"] = {
            "trend_label": "insufficient_data",
            "trend_score": 0,
            "reason": f"session momentum read error: {exc}",
        }
        log.warning(f"Session momentum unavailable for {symbol}: {exc}")

    return _session_observation(
        account_state.get("session_momentum") or {},
        account_state.get("session_momentum_gate") or {},
        account_state.get("session_gate_size_hint"),
    )


def build_buy_opportunity_observation(
    *,
    symbol: str,
    account_state: dict[str, Any],
    trend: dict[str, Any],
    bias_entry: dict[str, Any],
    evaluate_buy_opportunity: Callable[..., dict[str, Any]],
    required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    log: Any,
    prediction_gate: dict[str, Any] | None = None,
    log_prefix: str = "BUY opportunity",
) -> OpportunityObservation:
    setup_obs = account_state.get("setup_observation") or {}
    momentum = account_state.get("momentum") or {}
    recent_favorable_setup = account_state.get("recent_favorable_setup")

    adaptive_confirmation = required_buy_confirmations(symbol, account_state)
    account_state["adaptive_buy_confirmation"] = adaptive_confirmation

    opportunity = evaluate_buy_opportunity(
        trend=trend,
        setup_obs=setup_obs,
        bias_entry=bias_entry,
        macro_risk=account_state.get("macro_risk") or {},
        session_momentum=account_state.get("session_momentum") or {},
        momentum=momentum,
        prediction_gate=prediction_gate or {},
        recent_favorable_setup=recent_favorable_setup,
        adaptive_buy_confirmation=adaptive_confirmation,
    )
    opportunity.setdefault(
        "buy_opportunity_points_score",
        opportunity.get("buy_opportunity_score"),
    )
    opportunity.setdefault("score_scale", "points")
    account_state["buy_opportunity"] = opportunity

    log.info(
        f"{log_prefix} for {symbol}: "
        f"score={opportunity.get('buy_opportunity_score')} "
        f"recommendation={opportunity.get('buy_opportunity_recommendation')} "
        f"reason={opportunity.get('buy_opportunity_reason')}"
    )

    return _opportunity_observation(opportunity)


def build_trend_confirmation_observation(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any],
    trend_table: dict[str, dict[str, Any]],
    market_bias: dict[str, dict[str, Any]],
    current_et: datetime,
    required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    required_sell_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    is_fast_lane_buy_flip: Callable[..., bool],
    is_fast_lane_sell_flip: Callable[..., bool],
    market_open_minutes: int,
    open_momentum_fast_lane_enabled: bool,
    iex_thin_symbols: set[str],
) -> TrendObservation:
    trend = trend_table.get(symbol) or {}
    direction = trend.get("direction")
    strength = trend.get("strength")
    try:
        consecutive_count = int(trend.get("consecutive_count") or 0)
    except Exception:
        consecutive_count = 0
    last_signal = trend.get("last_signal")
    confirmation: dict[str, Any] = {
        "direction": direction,
        "strength": strength,
        "consecutive_count": consecutive_count,
        "last_signal": last_signal,
        "flip_event": trend.get("flip_event"),
    }

    if action == "buy":
        adaptive_confirmation = required_buy_confirmations(symbol, account_state)
        required = int(adaptive_confirmation.get("required_buy_confirmations") or 3)
        account_state["adaptive_buy_confirmation"] = adaptive_confirmation

        fast_lane_buy_flip = is_fast_lane_buy_flip(
            trend,
            required_buy_confirmations=required,
        )
        account_state["fast_lane_buy_flip"] = fast_lane_buy_flip

        momentum = account_state.get("momentum") or {}
        bias = (market_bias.get(symbol) or {}).get("bias")
        special_labels = (
            (account_state.get("rolling_momentum") or {}).get("special_labels") or []
        )
        session_elapsed_minutes = (
            current_et.hour * 60 + current_et.minute - market_open_minutes
        )
        volume_state = momentum.get("volume_state")
        volume_ok = (
            symbol in iex_thin_symbols
            and volume_state in ("normal", "elevated", "surge")
        ) or volume_state == "surge"
        open_momentum_fast_lane = open_momentum_fast_lane_enabled and (
            0 <= session_elapsed_minutes <= 60
            and momentum.get("momentum_state") == "accelerating"
            and volume_ok
            and bias == "buy"
            and "gap_up_chase_risk" not in special_labels
        )
        account_state["open_momentum_fast_lane"] = open_momentum_fast_lane

        confirmation.update(
            {
                "required_confirmations": required,
                "adaptive_confirmation": adaptive_confirmation,
                "fast_lane_buy_flip": fast_lane_buy_flip,
                "open_momentum_fast_lane": open_momentum_fast_lane,
                "session_elapsed_minutes": session_elapsed_minutes,
                "momentum_state": momentum.get("momentum_state"),
                "volume_state": volume_state,
                "volume_ok": volume_ok,
                "iex_thin": symbol in iex_thin_symbols,
                "bias": bias,
            }
        )

    elif action == "sell":
        sell_confirmation = required_sell_confirmations(symbol, account_state)
        required = int(sell_confirmation.get("required_sell_confirmations") or 2)
        account_state["sell_confirmation"] = sell_confirmation

        fast_lane_sell_flip = is_fast_lane_sell_flip(
            trend,
            required_sell_confirmations=required,
        )
        account_state["fast_lane_sell_flip"] = fast_lane_sell_flip

        confirmation.update(
            {
                "required_confirmations": required,
                "sell_confirmation": sell_confirmation,
                "fast_lane_sell_flip": fast_lane_sell_flip,
            }
        )

    return _trend_observation(trend, confirmation=confirmation)


def build_market_alignment_observation(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any],
    symbol_market_alignment: Callable[[str], dict[str, Any]],
    log: Any,
) -> MarketAlignmentObservation:
    current = account_state.get("market_alignment") or {}
    if current or action != "buy":
        return MarketAlignmentObservation(current)

    try:
        alignment = symbol_market_alignment(symbol)
        account_state["market_alignment"] = alignment
        return MarketAlignmentObservation(alignment)
    except Exception as exc:
        account_state["market_alignment_error"] = str(exc)
        log.warning(f"market alignment unavailable for {symbol}: {exc}")
        return MarketAlignmentObservation({})


def hydrate_pre_macro_context(
    context_runtime: SignalContextRuntime,
    *,
    get_macro_risk: Callable[[Any], dict[str, Any]],
    base_dir: Any,
    evaluate_buy_opportunity: Callable[..., dict[str, Any]],
    required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
) -> dict[str, Any]:
    """Populate non-authoritative context required before macro-position gates."""
    state = context_runtime.state
    account_state = context_runtime.account_state

    if state.action == "buy" and "buy_opportunity" not in account_state:
        try:
            context_runtime.build_buy_opportunity_observation(
                trend=context_runtime.deps.trend_table.get(state.symbol) or {},
                bias_entry=context_runtime.deps.market_bias.get(state.symbol) or {},
                evaluate_buy_opportunity=evaluate_buy_opportunity,
                required_buy_confirmations=required_buy_confirmations,
                log_prefix="BUY opportunity pre-macro",
            )
        except Exception as exc:
            context_runtime.deps.log.warning(
                f"BUY opportunity pre-macro scoring failed for {state.symbol}: {exc}"
            )

    macro_risk = get_macro_risk(base_dir)
    account_state["macro_risk"] = macro_risk
    return macro_risk


def apply_market_bias_context(
    *,
    action: str,
    account_state: dict[str, Any],
    bias_entry: dict[str, Any],
) -> None:
    """Inject market-bias metadata without making an approval decision."""
    if action != "buy" or not bias_entry:
        return

    bias = bias_entry.get("bias")
    account_state["market_bias_original"] = bias
    account_state["market_bias"] = bias
    account_state["avoid_type"] = bias_entry.get("avoid_type")
    account_state["soft_avoid_reason"] = bias_entry.get("reason", "")

    if bias_entry.get("fundamental_score"):
        account_state["fundamental_score"] = bias_entry["fundamental_score"]
    if bias_entry.get("risk_level"):
        account_state["risk_level"] = bias_entry["risk_level"]
    if bias_entry.get("entry_quality"):
        account_state["entry_quality"] = bias_entry["entry_quality"]

    # Preserve event-enriched market context in BUY decision state.
    # These fields are context/risk modifiers only. Single-source headline
    # events remain confidence-capped upstream and must not create standalone
    # BUY authority.
    for event_key in (
        "event_context",
        "catalyst_score",
        "consumer_appetite_score",
        "revenue_impact_score",
        "profit_potential_score",
        "margin_risk_score",
        "supply_chain_risk_score",
        "materials_risk_score",
        "competitive_risk_score",
        "execution_risk_score",
        "key_catalysts",
        "key_risks",
    ):
        if bias_entry.get(event_key) is not None:
            account_state[event_key] = bias_entry.get(event_key)


def hydrate_buy_momentum_context(context_runtime: SignalContextRuntime) -> None:
    state = context_runtime.state
    if state.action != "buy":
        return

    account_state = context_runtime.account_state
    context_runtime.hydrate_buy_live_context(only_missing=True)
    momentum = account_state.get("momentum")
    if not momentum:
        return

    alignment = momentum.get("premarket_alignment")
    action_hint = momentum.get("action_hint")
    symbol = state.symbol

    if alignment == "contradicted":
        account_state["signal_confidence_hint"] = "low"
        context_runtime.deps.log.warning(
            f"Pre-market alignment contradicted for {symbol} BUY: "
            f"bias={momentum.get('premarket_bias')} "
            f"5m={momentum.get('momentum_5m_pct')}% "
            f"15m={momentum.get('momentum_15m_pct')}% "
            f"hint={action_hint} — confidence hint set to low"
        )

    elif alignment == "confirmed":
        account_state["signal_confidence_hint"] = "high"
        context_runtime.deps.log.info(
            f"Pre-market alignment confirmed for {symbol} BUY: "
            f"bias={momentum.get('premarket_bias')} "
            f"5m={momentum.get('momentum_5m_pct')}% "
            f"15m={momentum.get('momentum_15m_pct')}% "
            f"hint={action_hint} — confidence hint set to high"
        )

    elif momentum["direction"] == "falling" and momentum["momentum_pct"] < -0.15:
        account_state["signal_confidence_hint"] = "low"
        context_runtime.deps.log.warning(
            f"Momentum caution for {symbol} BUY: direction={momentum['direction']} "
            f"momentum_pct={momentum['momentum_pct']}% last_close={momentum['last_close']} "
            f"— downgrading confidence hint to low"
        )

    elif momentum["direction"] == "rising":
        account_state["signal_confidence_hint"] = "high"
        context_runtime.deps.log.info(
            f"Momentum confirms {symbol} BUY: direction={momentum['direction']} "
            f"momentum_pct={momentum['momentum_pct']}% — confidence hint set to high"
        )


def hydrate_strategy_context(
    context_runtime: SignalContextRuntime,
    *,
    strategy_engine_mode: str,
    evaluate_strategy_observe_only: Callable[..., Any],
    symbol_market_alignment: Callable[[str], dict[str, Any]],
    apply_size_cap: Callable[..., Any],
    env_float: Callable[[str, float], float],
) -> None:
    if strategy_engine_mode != "observe":
        return

    state = context_runtime.state
    account_state = context_runtime.account_state
    symbol = state.symbol
    action = state.action

    try:
        strategy_trend = context_runtime.deps.trend_table.get(symbol) or {}
        strategy_momentum = account_state.get("momentum") or {}
        strategy_alignment = context_runtime.build_market_alignment_observation(
            symbol_market_alignment=symbol_market_alignment,
        ).data

        strategy_result = evaluate_strategy_observe_only(
            symbol=symbol,
            action=action,
            account_state=account_state,
            trend=strategy_trend,
            momentum=strategy_momentum,
            market_alignment=strategy_alignment,
            tape=account_state.get("tape") or {},
        )
        strategy_observation = strategy_result.to_dict()
        account_state["strategy_observation"] = strategy_observation

        trader_brain = strategy_observation.get("trader_brain") or {}
        context_runtime.deps.log.info(
            f"Strategy observe for {symbol} {action.upper()}: "
            f"score={trader_brain.get('score')} "
            f"approved_by_scorer={trader_brain.get('approved_by_scorer')} "
            f"setup={trader_brain.get('setup_type')} "
            f"reason={trader_brain.get('reason')}"
        )

        if action == "buy":
            score = float(trader_brain.get("score") or 0)
            cap = None
            if score < 40:
                cap = env_float("STRATEGY_SCORE_LOW_SIZE_CAP_PCT", 0.70)
            elif score < 55:
                cap = env_float("STRATEGY_SCORE_BELOW_THRESHOLD_SIZE_CAP_PCT", 0.85)
            if cap is not None:
                apply_size_cap(
                    account_state,
                    cap_pct=cap,
                    state_key="strategy_score_size_cap",
                    payload={"score": score, "cap_pct": cap},
                )
                context_runtime.deps.log.info(
                    f"Strategy score size cap for {symbol}: "
                    f"score={score:.1f} → {cap}%"
                )

    except Exception as exc:
        context_runtime.deps.log.warning(
            f"Strategy observe failed for {symbol} {action.upper()}: {exc}"
        )


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _prediction_observation(prediction: dict[str, Any]) -> PredictionObservation:
    score = _float_or_none(prediction.get("ml_prediction_score"))
    if score is None:
        score = _float_or_none(prediction.get("prediction_score"))
    sample_size = prediction.get("ml_prediction_sample_size")
    try:
        sample_size = int(sample_size or 0)
    except Exception:
        sample_size = 0
    return PredictionObservation(
        data=prediction,
        score=score,
        bucket=prediction.get("ml_prediction_bucket") or "unknown",
        sample_size=sample_size,
        confidence=prediction.get("ml_prediction_confidence"),
        decision=prediction.get("prediction_decision"),
        reason=prediction.get("prediction_reason") or prediction.get("ml_prediction_reason"),
    )


def _session_observation(
    session: dict[str, Any],
    gate: dict[str, Any],
    size_hint: str | None = None,
) -> SessionMomentumObservation:
    return SessionMomentumObservation(
        data=session,
        gate=gate,
        label=session.get("trend_label"),
        score=_float_or_none(session.get("trend_score")),
        severity=gate.get("severity"),
        would_block=bool(gate.get("would_block")),
        size_hint=size_hint,
    )


def _trend_observation(
    trend: dict[str, Any],
    *,
    confirmation: dict[str, Any] | None = None,
) -> TrendObservation:
    try:
        consecutive_count = int(trend.get("consecutive_count") or 0)
    except Exception:
        consecutive_count = 0
    return TrendObservation(
        data=trend,
        direction=trend.get("direction"),
        strength=trend.get("strength"),
        consecutive_count=consecutive_count,
        last_signal=trend.get("last_signal"),
        confirmation=confirmation or {},
    )


def _opportunity_observation(opportunity: dict[str, Any]) -> OpportunityObservation:
    reasons = opportunity.get("reason_codes")
    if reasons is None:
        reason = opportunity.get("buy_opportunity_reason")
        reasons = [reason] if reason else []
    return OpportunityObservation(
        data=opportunity,
        score=_float_or_none(opportunity.get("buy_opportunity_score") or opportunity.get("score")),
        bucket=opportunity.get("bucket"),
        recommendation=(
            opportunity.get("buy_opportunity_recommendation")
            or opportunity.get("decision")
        ),
        reasons=list(reasons) if isinstance(reasons, (list, tuple)) else [reasons],
        cap=_float_or_none(opportunity.get("cap") or opportunity.get("size_cap_pct")),
    )


def _market_regime_observation(regime: dict[str, Any]) -> MarketRegimeObservation:
    weights = regime.get("strategy_weights")
    return MarketRegimeObservation(
        data=regime,
        composite_regime=regime.get("composite_regime"),
        trend_regime=regime.get("trend_regime"),
        volatility_regime=regime.get("volatility_regime"),
        confidence=regime.get("confidence"),
        strategy_weights=weights if isinstance(weights, dict) else {},
    )


def _market_microstructure_observation(
    microstructure: dict[str, Any],
) -> MarketMicrostructureObservation:
    return MarketMicrostructureObservation(
        data=microstructure,
        session_phase=microstructure.get("session_phase"),
        breakout_quality=microstructure.get("breakout_quality"),
        liquidity_state=microstructure.get("liquidity_state"),
        reversion_risk=microstructure.get("reversion_risk"),
        expectancy_modifier=_float_or_none(microstructure.get("expectancy_modifier")) or 1.0,
    )


def _market_participation_observation(
    participation: dict[str, Any],
) -> MarketParticipationObservation:
    return MarketParticipationObservation(
        data=participation,
        participation_state=participation.get("participation_state"),
        confirmation_score=_float_or_none(participation.get("confirmation_score")) or 0.0,
        isolated_move_risk=participation.get("isolated_move_risk"),
        expectancy_modifier=_float_or_none(participation.get("expectancy_modifier")) or 1.0,
    )


def _volatility_normalization_observation(
    volatility: dict[str, Any],
) -> VolatilityNormalizationObservation:
    return VolatilityNormalizationObservation(
        data=volatility,
        stretch_state=volatility.get("stretch_state"),
        chase_risk=volatility.get("chase_risk"),
        volatility_adjusted_score=_float_or_none(
            volatility.get("volatility_adjusted_score")
        )
        or 0.0,
        expectancy_modifier=_float_or_none(volatility.get("expectancy_modifier")) or 1.0,
    )


def _downside_asymmetry_observation(
    downside: dict[str, Any],
) -> DownsideAsymmetryObservation:
    return DownsideAsymmetryObservation(
        data=downside,
        downside_state=downside.get("downside_state"),
        downside_score=_float_or_none(downside.get("downside_score")) or 0.0,
        expected_adverse_modifier=_float_or_none(
            downside.get("expected_adverse_modifier")
        )
        or 1.0,
    )


def _exit_decision_quality_observation(
    exit_quality: dict[str, Any],
) -> ExitDecisionQualityObservation:
    return ExitDecisionQualityObservation(
        data=exit_quality,
        exit_pressure_state=exit_quality.get("exit_pressure_state"),
        exit_quality_score=_float_or_none(exit_quality.get("exit_quality_score")) or 0.0,
        recommended_action=exit_quality.get("recommended_action"),
    )


def _portfolio_observation(portfolio: dict[str, Any]) -> PortfolioObservation:
    return PortfolioObservation(
        data=portfolio,
        decision=portfolio.get("decision"),
        size_multiplier=_float_or_none(portfolio.get("size_multiplier")) or 1.0,
        duplicate_risk_score=_float_or_none(portfolio.get("duplicate_risk_score")) or 0.0,
    )


def _execution_quality_observation(execution_quality: dict[str, Any]) -> ExecutionQualityObservation:
    return ExecutionQualityObservation(
        data=execution_quality,
        decision=execution_quality.get("decision"),
        fill_quality=execution_quality.get("fill_quality"),
        net_execution_cost_pct=_float_or_none(
            execution_quality.get("net_execution_cost_pct")
        ) or 0.0,
    )


def build_final_signal_context(
    *,
    account_state: dict[str, Any],
    trend_table: dict[str, Any],
    intelligence_context: dict[str, Any] | None = None,
    claude_account_state: dict[str, Any] | None = None,
) -> BuiltSignalContext:
    account_state["trend_table"] = trend_table

    setup = account_state.get("setup_observation") or {}
    setup_quality = account_state.get("setup_quality") or setup.get("setup_quality") or {}
    prediction = account_state.get("prediction_gate") or {}
    session = account_state.get("session_momentum") or {}
    session_gate = account_state.get("session_momentum_gate") or {}
    symbol = account_state.get("symbol")
    trend = trend_table.get(symbol) if symbol else {}
    trend = trend or {}
    strategy = account_state.get("strategy_observation") or {}
    market_alignment = account_state.get("market_alignment") or {}
    market_regime = account_state.get("market_regime") or classify_market_regime(
        account_state=account_state,
        market_context=market_alignment,
    ).to_dict()
    account_state["market_regime"] = market_regime
    market_microstructure = (
        account_state.get("market_microstructure")
        or classify_market_microstructure(account_state=account_state).to_dict()
    )
    account_state["market_microstructure"] = market_microstructure
    market_participation = (
        account_state.get("market_participation")
        or evaluate_market_participation(
            account_state=account_state,
            market_context=market_alignment,
        ).to_dict()
    )
    account_state["market_participation"] = market_participation
    volatility_normalization = (
        account_state.get("volatility_normalization")
        or classify_volatility_normalization(account_state=account_state).to_dict()
    )
    account_state["volatility_normalization"] = volatility_normalization
    downside_asymmetry = (
        account_state.get("downside_asymmetry")
        or evaluate_downside_asymmetry(account_state=account_state).to_dict()
    )
    account_state["downside_asymmetry"] = downside_asymmetry
    exit_decision_quality = (
        account_state.get("exit_decision_quality")
        or evaluate_exit_decision_quality(account_state=account_state).to_dict()
    )
    account_state["exit_decision_quality"] = exit_decision_quality
    portfolio_decision = account_state.get("portfolio_decision") or evaluate_portfolio_decision(
        symbol=str(symbol or ""),
        action=str(account_state.get("action") or ""),
        account_state=account_state,
    ).to_dict()
    account_state["portfolio_decision"] = portfolio_decision
    execution_quality = account_state.get("execution_quality") or estimate_execution_quality(
        symbol=str(symbol or ""),
        action=str(account_state.get("action") or ""),
        signal_price=account_state.get("signal_price"),
        account_state=account_state,
    ).to_dict()
    account_state["execution_quality"] = execution_quality
    opportunity = account_state.get("buy_opportunity") or {}
    intelligence_context = intelligence_context or account_state.get("intelligence_context") or {}
    claude_account_state = build_claude_account_state(account_state)

    decision_context = {
        "setup": setup,
        "setup_quality": setup_quality,
        "prediction": prediction,
        "session_momentum": session,
        "session_momentum_gate": session_gate,
        "strategy": strategy,
        "market_alignment": market_alignment,
        "market_regime": market_regime,
        "market_microstructure": market_microstructure,
        "market_participation": market_participation,
        "volatility_normalization": volatility_normalization,
        "downside_asymmetry": downside_asymmetry,
        "exit_decision_quality": exit_decision_quality,
        "portfolio_decision": portfolio_decision,
        "execution_quality": execution_quality,
        "intelligence_context": intelligence_context,
    }

    summary = {
        "setup_label": setup_quality.get("label") or setup.get("setup_label"),
        "setup_recommendation": setup_quality.get("recommendation"),
        "setup_quality_source": setup_quality.get("source"),
        "setup_quality_recommendation": setup_quality.get("recommendation"),
        "setup_policy_action": setup.get("setup_policy_action"),
        "prediction_score": prediction.get("prediction_score"),
        "prediction_decision": prediction.get("prediction_decision"),
        "session_trend_label": session.get("trend_label"),
        "session_trend_score": session.get("trend_score"),
        "session_gate_severity": session_gate.get("severity"),
        "session_gate_would_block": session_gate.get("would_block"),
        "effective_bias": account_state.get("market_bias_effective"),
        "market_regime": market_regime.get("composite_regime"),
        "market_regime_confidence": market_regime.get("confidence"),
        "session_phase": market_microstructure.get("session_phase"),
        "breakout_quality": market_microstructure.get("breakout_quality"),
        "microstructure_score": market_microstructure.get("microstructure_score"),
        "microstructure_expectancy_modifier": market_microstructure.get(
            "expectancy_modifier"
        ),
        "participation_state": market_participation.get("participation_state"),
        "participation_confirmation_score": market_participation.get(
            "confirmation_score"
        ),
        "isolated_move_risk": market_participation.get("isolated_move_risk"),
        "volatility_stretch_state": volatility_normalization.get("stretch_state"),
        "volatility_chase_risk": volatility_normalization.get("chase_risk"),
        "volatility_adjusted_score": volatility_normalization.get(
            "volatility_adjusted_score"
        ),
        "downside_state": downside_asymmetry.get("downside_state"),
        "downside_score": downside_asymmetry.get("downside_score"),
        "exit_pressure_state": exit_decision_quality.get("exit_pressure_state"),
        "exit_quality_score": exit_decision_quality.get("exit_quality_score"),
        "portfolio_decision": portfolio_decision.get("decision"),
        "portfolio_duplicate_risk_score": portfolio_decision.get("duplicate_risk_score"),
        "execution_quality": execution_quality.get("fill_quality"),
        "net_execution_cost_pct": execution_quality.get("net_execution_cost_pct"),
    }

    return BuiltSignalContext(
        account_state=account_state,
        decision_context=decision_context,
        setup=SetupObservation(setup),
        prediction=_prediction_observation(prediction),
        session=_session_observation(
            session,
            session_gate,
            account_state.get("session_gate_size_hint"),
        ),
        trend=_trend_observation(trend),
        strategy=StrategyObservation(strategy),
        market_alignment=MarketAlignmentObservation(market_alignment),
        market_regime=_market_regime_observation(market_regime),
        market_microstructure=_market_microstructure_observation(market_microstructure),
        market_participation=_market_participation_observation(market_participation),
        volatility_normalization=_volatility_normalization_observation(
            volatility_normalization
        ),
        downside_asymmetry=_downside_asymmetry_observation(downside_asymmetry),
        exit_decision_quality=_exit_decision_quality_observation(
            exit_decision_quality
        ),
        portfolio=_portfolio_observation(portfolio_decision),
        execution_quality=_execution_quality_observation(execution_quality),
        opportunity=_opportunity_observation(opportunity),
        claude_account_state=claude_account_state,
        summary=summary,
    )


class ContextBuilder:
    def build(self, signal: SignalContext) -> DecisionContext:
        return DecisionContext(signal=signal)
