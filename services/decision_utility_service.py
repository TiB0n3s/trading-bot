"""Observe-only probabilistic edge and decision utility estimation.

This module estimates probabilistic edge and expected utility from already-built
decision context. It does not approve trades, reject trades, size orders, fetch
data, or submit orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProbabilisticEdgeEstimate:
    probability_favorable_move: float
    expected_upside_pct: float
    expected_adverse_excursion_pct: float
    holding_time_decay_pct: float
    confidence: str
    edge_quality: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionUtilityEstimate:
    edge_estimate: ProbabilisticEdgeEstimate
    slippage_fee_pct: float
    execution_cost_pct: float
    expected_value_pct: float
    portfolio_adjusted_utility_pct: float
    utility_threshold_pct: float
    utility_decision: str
    utility_scope: str = "telemetry_observe_only"
    threshold_scope: str = "diagnostic_not_live_policy"

    @property
    def probability_favorable_move(self) -> float:
        return self.edge_estimate.probability_favorable_move

    @property
    def expected_upside_pct(self) -> float:
        return self.edge_estimate.expected_upside_pct

    @property
    def expected_adverse_excursion_pct(self) -> float:
        return self.edge_estimate.expected_adverse_excursion_pct

    @property
    def holding_time_decay_pct(self) -> float:
        return self.edge_estimate.holding_time_decay_pct

    @property
    def confidence(self) -> str:
        return self.edge_estimate.confidence

    @property
    def reasons(self) -> list[str]:
        return self.edge_estimate.reasons

    def to_dict(self) -> dict[str, Any]:
        edge = self.edge_estimate.to_dict()
        return {
            **edge,
            "edge_estimate": edge,
            "slippage_fee_pct": self.slippage_fee_pct,
            "execution_cost_pct": self.execution_cost_pct,
            "expected_value_pct": self.expected_value_pct,
            "telemetry_expected_value_pct": self.expected_value_pct,
            "portfolio_adjusted_utility_pct": self.portfolio_adjusted_utility_pct,
            "telemetry_portfolio_adjusted_utility_pct": self.portfolio_adjusted_utility_pct,
            "utility_threshold_pct": self.utility_threshold_pct,
            "utility_decision": self.utility_decision,
            "telemetry_utility_decision": self.utility_decision,
            "utility_scope": self.utility_scope,
            "threshold_scope": self.threshold_scope,
        }


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _score_to_unit(value: Any, *, high_scale: float = 100.0) -> float | None:
    score = _float(value)
    if score is None:
        return None
    return _clamp(score / high_scale, 0.0, 1.0)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}


def estimate_probabilistic_edge(
    *,
    action: str,
    intelligence_context: dict[str, Any] | None = None,
    account_state: dict[str, Any] | None = None,
) -> ProbabilisticEdgeEstimate:
    """Build an observe-only probabilistic edge estimate from existing context.

    The estimate is intentionally conservative and deterministic. It is a
    telemetry layer for calibration, not an authority layer.
    """
    action = (action or "").lower()
    intelligence_context = _dict(intelligence_context)
    account_state = _dict(account_state)
    reasons: list[str] = []

    if action != "buy":
        return ProbabilisticEdgeEstimate(
            probability_favorable_move=0.0,
            expected_upside_pct=0.0,
            expected_adverse_excursion_pct=0.0,
            holding_time_decay_pct=0.0,
            confidence="none",
            edge_quality=0.0,
            reasons=["sell signal: utility estimate is buy-side only"],
        )

    opportunity = _first_dict(
        intelligence_context.get("opportunity_score"),
        intelligence_context.get("buy_opportunity"),
        account_state.get("opportunity_score"),
        account_state.get("buy_opportunity"),
    )
    buy_opportunity = _dict(account_state.get("buy_opportunity"))
    setup_quality = _dict(account_state.get("setup_quality"))
    setup_observation = _dict(account_state.get("setup_observation"))
    momentum = _dict(account_state.get("momentum"))
    prediction = _first_dict(
        intelligence_context.get("prediction"),
        account_state.get("prediction_gate"),
    )
    strategy = _dict(account_state.get("strategy_observation"))
    trader_brain = _dict(strategy.get("trader_brain"))
    session_gate = _dict(account_state.get("session_momentum_gate"))
    market_regime = _dict(account_state.get("market_regime"))
    calibrated_confidence = _dict(account_state.get("calibrated_confidence"))
    portfolio_decision = _dict(account_state.get("portfolio_decision"))
    execution_quality = _dict(account_state.get("execution_quality"))
    microstructure = _dict(account_state.get("market_microstructure"))
    participation = _dict(account_state.get("market_participation"))
    volatility = _dict(account_state.get("volatility_normalization"))
    downside = _dict(account_state.get("downside_asymmetry"))

    opportunity_unit = _score_to_unit(
        opportunity.get("score")
        or buy_opportunity.get("buy_opportunity_score"),
        high_scale=100.0,
    )
    if opportunity_unit is not None:
        reasons.append(f"opportunity_score_unit={opportunity_unit:.2f}")

    setup_unit = _score_to_unit(
        setup_quality.get("score") or setup_observation.get("setup_score"),
        high_scale=100.0,
    )
    if setup_unit is not None:
        reasons.append(f"setup_score_unit={setup_unit:.2f}")
    setup_structure = _dict(setup_quality.get("structure"))
    structure_score_unit = _score_to_unit(setup_structure.get("structure_score"), high_scale=1.0)
    if structure_score_unit is not None:
        reasons.append(f"setup_structure_unit={structure_score_unit:.2f}")

    strategy_unit = _score_to_unit(trader_brain.get("score"), high_scale=100.0)
    if strategy_unit is not None:
        reasons.append(f"strategy_score_unit={strategy_unit:.2f}")

    ml_unit = _score_to_unit(prediction.get("ml_prediction_score"), high_scale=100.0)
    if ml_unit is not None:
        reasons.append(f"ml_prediction_unit={ml_unit:.2f}")

    usable_units = [
        value
        for value in (
            opportunity_unit,
            setup_unit,
            structure_score_unit,
            strategy_unit,
            ml_unit,
        )
        if value is not None
    ]
    if usable_units:
        edge_quality = sum(usable_units) / len(usable_units)
        confidence = "medium" if len(usable_units) >= 2 else "low"
    else:
        edge_quality = 0.5
        confidence = "low"
        reasons.append("no calibrated scores available; neutral prior used")

    probability = 0.38 + 0.38 * edge_quality

    session_severity = session_gate.get("severity")
    if session_severity == "pass":
        probability += 0.04
        reasons.append("session_momentum supportive")
    elif session_severity in {"soft_negative", "reversal_caution"}:
        probability -= 0.06
        reasons.append(f"session_momentum caution={session_severity}")
    elif session_severity == "hard_negative":
        probability -= 0.12
        reasons.append("session_momentum hard_negative")

    setup_recommendation = setup_quality.get("recommendation")
    if setup_recommendation in {"favorable", "buy"}:
        probability += 0.04
        reasons.append(f"setup_quality supportive={setup_recommendation}")
    elif setup_recommendation == "watch":
        probability -= 0.04
        reasons.append("setup_quality watch")
    elif setup_recommendation == "avoid":
        probability -= 0.10
        reasons.append("setup_quality avoid")

    ml_decision = prediction.get("ml_prediction_compare_decision")
    if ml_decision in {"avoid", "block", "caution"}:
        probability -= 0.08
        reasons.append(f"ml_compare negative={ml_decision}")
    elif ml_decision in {"pass", "allow", "buy"}:
        probability += 0.03
        reasons.append(f"ml_compare supportive={ml_decision}")

    regime_weights = _dict(market_regime.get("strategy_weights"))
    composite_regime = market_regime.get("composite_regime")
    liquidity_regime = market_regime.get("liquidity_regime")
    setup_label = str(
        setup_quality.get("label") or setup_observation.get("setup_label") or ""
    ).lower()

    trend_weight = _float(regime_weights.get("trend_continuation"))
    pullback_weight = _float(regime_weights.get("orderly_pullback"))
    mean_reversion_weight = _float(regime_weights.get("mean_reversion"))
    chase_weight = _float(regime_weights.get("momentum_chase"))

    if composite_regime:
        reasons.append(f"market_regime={composite_regime}")

    if (
        trend_weight is not None
        and trend_weight >= 1.15
        and momentum.get("direction") == "rising"
    ):
        probability += 0.04
        reasons.append("regime favors trend continuation")
    if (
        pullback_weight is not None
        and pullback_weight >= 1.10
        and any(token in setup_label for token in ("pullback", "vwap", "recovery"))
    ):
        probability += 0.03
        reasons.append("regime favors orderly pullbacks")
    if (
        mean_reversion_weight is not None
        and mean_reversion_weight >= 1.15
        and any(token in setup_label for token in ("oversold", "bounce", "reversal"))
    ):
        probability += 0.03
        reasons.append("regime favors mean reversion")
    if (
        chase_weight is not None
        and chase_weight <= 0.70
        and any(token in setup_label for token in ("breakout", "momentum", "chase"))
    ):
        probability -= 0.05
        reasons.append("regime penalizes momentum chase")
    if liquidity_regime == "liquidity_thin":
        probability -= 0.05
        reasons.append("liquidity-thin regime penalty")

    session_phase = microstructure.get("session_phase")
    breakout_quality = microstructure.get("breakout_quality")
    liquidity_state = microstructure.get("liquidity_state")
    reversion_risk = microstructure.get("reversion_risk")
    microstructure_score = _float(microstructure.get("microstructure_score"))
    expectancy_modifier = _float(microstructure.get("expectancy_modifier"))
    if session_phase:
        reasons.append(f"session_phase={session_phase}")
    if microstructure_score is not None:
        probability += (microstructure_score - 0.50) * 0.16
        reasons.append(f"microstructure_score={microstructure_score:.2f}")
    if breakout_quality in {"confirmed_expansion_breakout", "power_hour_expansion"}:
        probability += 0.04
        reasons.append(f"microstructure_support={breakout_quality}")
    elif breakout_quality == "liquidity_vacuum_breakout":
        probability -= 0.07
        reasons.append("liquidity_vacuum_breakout")
    if liquidity_state in {"midday_liquidity_decay", "liquidity_vacuum"}:
        probability -= 0.04
        reasons.append(f"microstructure_liquidity={liquidity_state}")
    if reversion_risk == "high":
        probability -= 0.06
        reasons.append("high_microstructure_reversion_risk")
    elif reversion_risk == "elevated":
        probability -= 0.03
        reasons.append("elevated_microstructure_reversion_risk")

    participation_state = participation.get("participation_state")
    isolated_move_risk = participation.get("isolated_move_risk")
    confirmation_score = _float(participation.get("confirmation_score"))
    participation_modifier = _float(participation.get("expectancy_modifier"))
    if participation_state:
        reasons.append(f"participation_state={participation_state}")
    if confirmation_score is not None:
        probability += (confirmation_score - 0.50) * 0.18
        reasons.append(f"participation_score={confirmation_score:.2f}")
    if participation_state == "confirmed":
        probability += 0.05
        reasons.append("market_participation_confirmed")
    elif participation_state == "isolated_or_weak":
        probability -= 0.08
        reasons.append("isolated_or_weak_market_participation")
    if isolated_move_risk == "high":
        probability -= 0.07
        reasons.append("high_isolated_move_risk")
    elif isolated_move_risk == "elevated":
        probability -= 0.04
        reasons.append("elevated_isolated_move_risk")

    volatility_score = _float(volatility.get("volatility_adjusted_score"))
    volatility_modifier = _float(volatility.get("expectancy_modifier"))
    stretch_state = volatility.get("stretch_state")
    chase_risk = volatility.get("chase_risk")
    stop_quality = volatility.get("stop_quality")
    if volatility_score is not None:
        probability += (volatility_score - 0.50) * 0.16
        reasons.append(f"volatility_adjusted_score={volatility_score:.2f}")
    if chase_risk == "high":
        probability -= 0.08
        reasons.append("high_volatility_normalized_chase_risk")
    elif chase_risk == "elevated":
        probability -= 0.04
        reasons.append("elevated_volatility_normalized_chase_risk")
    if stretch_state in {"stretched", "extreme_stretch"}:
        probability -= 0.03
        reasons.append(f"volatility_stretch={stretch_state}")
    if stop_quality == "aligned_with_excursion":
        probability += 0.02
        reasons.append("stop_distance_aligned_with_excursion")
    elif stop_quality in {"too_tight_vs_excursion", "too_wide_vs_excursion"}:
        probability -= 0.03
        reasons.append(f"stop_quality={stop_quality}")

    downside_score = _float(downside.get("downside_score"))
    adverse_modifier = _float(downside.get("expected_adverse_modifier"))
    downside_state = downside.get("downside_state")
    if downside_score is not None:
        probability -= downside_score * 0.12
        reasons.append(f"downside_score={downside_score:.2f}")
    if downside_state == "asymmetric_downside_high":
        probability -= 0.06
        reasons.append("asymmetric_downside_high")
    elif downside_state == "asymmetric_downside_elevated":
        probability -= 0.03
        reasons.append("asymmetric_downside_elevated")

    realized_win_rate = _float(calibrated_confidence.get("primary_realized_win_rate"))
    predicted_win_rate = _float(calibrated_confidence.get("primary_predicted_win_rate"))
    confidence_sample_size = _float(calibrated_confidence.get("primary_sample_size"))
    confidence_quality = calibrated_confidence.get("confidence_quality")
    calibrated_win_rate = realized_win_rate if realized_win_rate is not None else predicted_win_rate
    if calibrated_win_rate is not None and confidence_quality != "uncalibrated_prior":
        blend_weight = 0.35 if (confidence_sample_size or 0) >= 20 else 0.20
        probability = probability * (1.0 - blend_weight) + calibrated_win_rate * blend_weight
        reasons.append(
            f"calibrated_confidence_blend={calibrated_win_rate:.2f}/w={blend_weight:.2f}"
        )

    portfolio_action = portfolio_decision.get("decision")
    if portfolio_action == "block":
        probability -= 0.12
        reasons.append("portfolio duplicate risk block")
    elif portfolio_action == "size_down":
        probability -= 0.06
        reasons.append("portfolio duplicate risk size_down")

    execution_action = execution_quality.get("decision")
    if execution_action == "block":
        probability -= 0.10
        reasons.append("execution quality block")
    elif execution_action == "size_down":
        probability -= 0.05
        reasons.append("execution quality size_down")

    probability = round(_clamp(probability, 0.05, 0.95), 4)

    expected_upside_pct = round(0.25 + 1.35 * edge_quality, 4)
    expected_adverse_excursion_pct = round(0.25 + 0.95 * (1.0 - edge_quality), 4)
    if expectancy_modifier is not None:
        expected_upside_pct = round(expected_upside_pct * expectancy_modifier, 4)
        if expectancy_modifier < 1.0:
            expected_adverse_excursion_pct = round(
                expected_adverse_excursion_pct + (1.0 - expectancy_modifier) * 0.50,
                4,
            )
        elif expectancy_modifier > 1.0:
            expected_adverse_excursion_pct = round(
                max(0.05, expected_adverse_excursion_pct - (expectancy_modifier - 1.0) * 0.20),
                4,
            )
    if participation_modifier is not None:
        expected_upside_pct = round(expected_upside_pct * participation_modifier, 4)
        if participation_modifier < 1.0:
            expected_adverse_excursion_pct = round(
                expected_adverse_excursion_pct + (1.0 - participation_modifier) * 0.45,
                4,
            )
        elif participation_modifier > 1.0:
            expected_adverse_excursion_pct = round(
                max(
                    0.05,
                    expected_adverse_excursion_pct
                    - (participation_modifier - 1.0) * 0.18,
                ),
                4,
            )
    if volatility_modifier is not None:
        expected_upside_pct = round(expected_upside_pct * volatility_modifier, 4)
        if volatility_modifier < 1.0:
            expected_adverse_excursion_pct = round(
                expected_adverse_excursion_pct + (1.0 - volatility_modifier) * 0.55,
                4,
            )
        elif volatility_modifier > 1.0:
            expected_adverse_excursion_pct = round(
                max(
                    0.05,
                    expected_adverse_excursion_pct
                    - (volatility_modifier - 1.0) * 0.18,
                ),
                4,
            )
    structure_modifier = _float(setup_structure.get("expectancy_modifier"))
    if structure_modifier is not None:
        expected_upside_pct = round(expected_upside_pct * structure_modifier, 4)
        if structure_modifier < 1.0:
            expected_adverse_excursion_pct = round(
                expected_adverse_excursion_pct + (1.0 - structure_modifier) * 0.45,
                4,
            )
        elif structure_modifier > 1.0:
            expected_adverse_excursion_pct = round(
                max(0.05, expected_adverse_excursion_pct - (structure_modifier - 1.0) * 0.18),
                4,
            )
    if adverse_modifier is not None:
        expected_adverse_excursion_pct = round(
            expected_adverse_excursion_pct * max(1.0, adverse_modifier),
            4,
        )

    if trend_weight is not None and trend_weight >= 1.15:
        expected_upside_pct = round(expected_upside_pct + 0.10, 4)
    if chase_weight is not None and chase_weight <= 0.70:
        expected_adverse_excursion_pct = round(expected_adverse_excursion_pct + 0.10, 4)
    if liquidity_regime == "liquidity_thin":
        expected_adverse_excursion_pct = round(expected_adverse_excursion_pct + 0.15, 4)
    if portfolio_action in {"block", "size_down"}:
        expected_adverse_excursion_pct = round(
            expected_adverse_excursion_pct
            + float(portfolio_decision.get("incremental_var_pct") or 0.0) * 0.05,
            4,
        )
    if execution_action in {"block", "size_down"}:
        expected_adverse_excursion_pct = round(
            expected_adverse_excursion_pct
            + float(execution_quality.get("net_execution_cost_pct") or 0.0) * 0.10,
            4,
        )

    if session_severity in {"soft_negative", "reversal_caution"}:
        expected_adverse_excursion_pct = round(expected_adverse_excursion_pct + 0.15, 4)
    elif session_severity == "hard_negative":
        expected_adverse_excursion_pct = round(expected_adverse_excursion_pct + 0.30, 4)

    holding_time_decay_pct = 0.04
    if session_phase == "midday":
        holding_time_decay_pct += 0.03
    elif session_phase == "opening_auction":
        holding_time_decay_pct += 0.02
    elif session_phase == "power_hour" and breakout_quality == "power_hour_expansion":
        holding_time_decay_pct = max(0.02, holding_time_decay_pct - 0.01)
    if session_severity in {"reversal_caution", "fading"}:
        holding_time_decay_pct = 0.08
    elif session_severity in {"soft_negative", "hard_negative"}:
        holding_time_decay_pct = 0.12

    return ProbabilisticEdgeEstimate(
        probability_favorable_move=probability,
        expected_upside_pct=expected_upside_pct,
        expected_adverse_excursion_pct=expected_adverse_excursion_pct,
        holding_time_decay_pct=round(holding_time_decay_pct, 4),
        confidence=confidence,
        edge_quality=round(edge_quality, 4),
        reasons=reasons[:12],
    )


def estimate_decision_utility(
    *,
    action: str,
    intelligence_context: dict[str, Any] | None = None,
    account_state: dict[str, Any] | None = None,
    edge_estimate: ProbabilisticEdgeEstimate | None = None,
    utility_threshold_pct: float = 0.05,
    slippage_fee_pct: float = 0.03,
) -> DecisionUtilityEstimate:
    """Build an observe-only utility estimate from a probabilistic edge estimate."""
    action = (action or "").lower()
    account_state = _dict(account_state)
    portfolio_decision = _dict(account_state.get("portfolio_decision"))
    portfolio_action = portfolio_decision.get("decision")
    edge = edge_estimate or estimate_probabilistic_edge(
        action=action,
        intelligence_context=intelligence_context,
        account_state=account_state,
    )

    if action != "buy":
        return DecisionUtilityEstimate(
            edge_estimate=edge,
            slippage_fee_pct=0.0,
            execution_cost_pct=0.0,
            expected_value_pct=0.0,
            portfolio_adjusted_utility_pct=0.0,
            utility_threshold_pct=round(utility_threshold_pct, 4),
            utility_decision="not_applicable",
        )

    execution_quality = _dict(account_state.get("execution_quality"))
    execution_cost_pct = _float(execution_quality.get("net_execution_cost_pct"))
    if execution_cost_pct is None:
        execution_cost_pct = float(slippage_fee_pct or 0.0)

    expected_value_pct = round(
        edge.probability_favorable_move * edge.expected_upside_pct
        - (1.0 - edge.probability_favorable_move) * edge.expected_adverse_excursion_pct
        - edge.holding_time_decay_pct
        - execution_cost_pct,
        4,
    )

    macro_risk = _dict(account_state.get("macro_risk"))
    risk_multiplier = _float(macro_risk.get("risk_multiplier"))
    if risk_multiplier is None:
        risk_multiplier = 1.0
    portfolio_adjusted_utility_pct = round(expected_value_pct * risk_multiplier, 4)
    portfolio_multiplier = _float(portfolio_decision.get("size_multiplier"))
    if portfolio_multiplier is not None and portfolio_action in {"block", "size_down"}:
        portfolio_adjusted_utility_pct = round(
            portfolio_adjusted_utility_pct * max(0.0, min(1.0, portfolio_multiplier)),
            4,
        )
    execution_action = execution_quality.get("decision")
    execution_multiplier = _float(execution_quality.get("size_multiplier"))
    if execution_multiplier is not None and execution_action in {"block", "size_down"}:
        portfolio_adjusted_utility_pct = round(
            portfolio_adjusted_utility_pct * max(0.0, min(1.0, execution_multiplier)),
            4,
        )

    utility_decision = (
        "trade_candidate"
        if portfolio_adjusted_utility_pct > utility_threshold_pct
        else "do_not_trade"
    )

    return DecisionUtilityEstimate(
        edge_estimate=edge,
        slippage_fee_pct=round(slippage_fee_pct, 4),
        execution_cost_pct=round(execution_cost_pct, 4),
        expected_value_pct=expected_value_pct,
        portfolio_adjusted_utility_pct=portfolio_adjusted_utility_pct,
        utility_threshold_pct=round(utility_threshold_pct, 4),
        utility_decision=utility_decision,
    )
