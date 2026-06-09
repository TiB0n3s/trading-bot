"""Alternative-data gate for layered model decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

ALTERNATIVE_DATA_GATE_VERSION = "alternative_data_gate_v1"
ALTERNATIVE_DATA_GATE_RUNTIME_EFFECT = "model_gate_context_no_order_submission"


@dataclass(frozen=True)
class AlternativeDataGate:
    version: str
    runtime_effect: str
    decision: str
    size_modifier: float
    stress_score: float
    text_sentiment: dict[str, Any]
    liquidity_footprints: dict[str, Any]
    intermarket_effects: dict[str, Any]
    hardware_telemetry: dict[str, Any]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
    except Exception:
        return None
    return result if result == result else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _float(value)
        if parsed is not None:
            return parsed
    return None


def _z_score(value: Any, mean: Any, std: Any) -> float | None:
    current = _float(value)
    baseline = _float(mean)
    sigma = _float(std)
    if current is None or baseline is None or sigma is None or sigma <= 0:
        return None
    return (current - baseline) / sigma


def _nested(account_state: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = _dict(account_state.get(key))
        if value:
            return value
    return {}


def _text_sentiment(
    account_state: dict[str, Any], action: str
) -> tuple[dict[str, Any], float, list[str]]:
    text = _nested(
        account_state,
        "text_sentiment",
        "financial_sentiment",
        "sentiment",
        "sec_sentiment",
    )
    velocity = _first_float(
        text.get("sentiment_velocity"),
        text.get("tone_velocity"),
        text.get("semantic_shift_score"),
        account_state.get("sentiment_velocity"),
    )
    score = _first_float(
        text.get("sentiment_score"),
        text.get("compound_score"),
        text.get("score"),
        account_state.get("sentiment_score"),
    )
    anomaly = _first_float(text.get("anomaly_score"), text.get("unexpected_tone_score"))
    entropy = _first_float(
        text.get("text_entropy"),
        text.get("sentiment_entropy"),
        text.get("news_disagreement_entropy"),
        account_state.get("text_entropy"),
    )
    stress = 0.0
    reasons: list[str] = []
    action_l = str(action or "").lower()
    if score is not None:
        adverse = score < -0.35 if action_l == "buy" else score > 0.35
        if adverse:
            stress += _clamp(abs(score) * 45.0)
            reasons.append(f"adverse_sentiment_score={score:.3f}")
    if velocity is not None:
        adverse_velocity = velocity < -0.25 if action_l == "buy" else velocity > 0.25
        if adverse_velocity:
            stress += _clamp(abs(velocity) * 35.0)
            reasons.append(f"adverse_sentiment_velocity={velocity:.3f}")
    if anomaly is not None and anomaly >= 0.70:
        stress += _clamp(anomaly * 25.0)
        reasons.append(f"text_anomaly_score={anomaly:.3f}")
    if entropy is not None and entropy >= 0.70:
        stress += _clamp(entropy * 30.0)
        reasons.append(f"text_entropy={entropy:.3f}")
    return (
        {
            "present": bool(text),
            "sentiment_score": score,
            "sentiment_velocity": velocity,
            "anomaly_score": anomaly,
            "text_entropy": entropy,
        },
        _clamp(stress),
        reasons,
    )


def _liquidity_footprints(account_state: dict[str, Any]) -> tuple[dict[str, Any], float, list[str]]:
    liquidity = _nested(
        account_state,
        "liquidity_footprints",
        "options_microstructure",
        "dark_pool",
        "market_microstructure",
    )
    gamma_risk = _first_float(
        liquidity.get("gamma_exposure_risk"),
        liquidity.get("gamma_squeeze_risk"),
        liquidity.get("option_gamma_risk"),
    )
    skew_risk = _first_float(
        liquidity.get("put_call_skew_risk"),
        liquidity.get("options_skew_risk"),
        liquidity.get("vanna_risk"),
    )
    dark_pool_imbalance = _first_float(
        liquidity.get("dark_pool_imbalance"),
        liquidity.get("block_trade_imbalance"),
        liquidity.get("institutional_flow_imbalance"),
    )
    stress = 0.0
    reasons: list[str] = []
    if gamma_risk is not None and gamma_risk >= 0.65:
        stress += _clamp(gamma_risk * 45.0)
        reasons.append(f"gamma_risk={gamma_risk:.3f}")
    if skew_risk is not None and skew_risk >= 0.60:
        stress += _clamp(skew_risk * 35.0)
        reasons.append(f"options_skew_risk={skew_risk:.3f}")
    if dark_pool_imbalance is not None and abs(dark_pool_imbalance) >= 0.65:
        stress += _clamp(abs(dark_pool_imbalance) * 30.0)
        reasons.append(f"dark_pool_imbalance={dark_pool_imbalance:.3f}")
    return (
        {
            "present": bool(liquidity),
            "gamma_exposure_risk": gamma_risk,
            "options_skew_risk": skew_risk,
            "dark_pool_imbalance": dark_pool_imbalance,
        },
        _clamp(stress),
        reasons,
    )


def _intermarket_effects(
    account_state: dict[str, Any], action: str
) -> tuple[dict[str, Any], float, list[str]]:
    intermarket = _nested(
        account_state,
        "intermarket_effects",
        "macro_cross_asset",
        "cross_asset",
        "market_context",
    )
    yield_spike = _first_float(
        intermarket.get("yield_curve_spike_score"),
        intermarket.get("two_ten_yield_stress"),
        intermarket.get("rate_shock_score"),
    )
    dollar_stress = _first_float(
        intermarket.get("dxy_stress_score"),
        intermarket.get("usd_jpy_volatility_score"),
        intermarket.get("currency_stress_score"),
    )
    commodity_shock = _first_float(
        intermarket.get("commodity_shock_score"),
        intermarket.get("oil_shock_score"),
        intermarket.get("gold_shock_score"),
    )
    correlation_break = _first_float(
        intermarket.get("correlation_break_score"),
        intermarket.get("cross_asset_correlation_stress"),
    )
    stress = 0.0
    reasons: list[str] = []
    action_l = str(action or "").lower()
    if yield_spike is not None and yield_spike >= 0.60 and action_l == "buy":
        stress += _clamp(yield_spike * 40.0)
        reasons.append(f"yield_curve_stress={yield_spike:.3f}")
    if dollar_stress is not None and dollar_stress >= 0.60:
        stress += _clamp(dollar_stress * 25.0)
        reasons.append(f"currency_stress={dollar_stress:.3f}")
    if commodity_shock is not None and commodity_shock >= 0.65:
        stress += _clamp(commodity_shock * 25.0)
        reasons.append(f"commodity_shock={commodity_shock:.3f}")
    if correlation_break is not None and correlation_break >= 0.60:
        stress += _clamp(correlation_break * 30.0)
        reasons.append(f"correlation_break={correlation_break:.3f}")
    return (
        {
            "present": bool(intermarket),
            "yield_curve_spike_score": yield_spike,
            "currency_stress_score": dollar_stress,
            "commodity_shock_score": commodity_shock,
            "correlation_break_score": correlation_break,
        },
        _clamp(stress),
        reasons,
    )


def _hardware_telemetry(account_state: dict[str, Any]) -> tuple[dict[str, Any], float, list[str]]:
    telemetry = _nested(
        account_state,
        "hardware_telemetry",
        "execution_telemetry",
        "infrastructure_telemetry",
        "api_telemetry",
    )
    latency_ms = _first_float(
        telemetry.get("api_latency_ms"),
        telemetry.get("broker_latency_ms"),
        telemetry.get("round_trip_latency_ms"),
        account_state.get("api_latency_ms"),
    )
    fill_ms = _first_float(telemetry.get("avg_fill_time_ms"), telemetry.get("broker_queue_ms"))
    error_rate = _first_float(telemetry.get("api_error_rate"), telemetry.get("broker_error_rate"))
    spread_expansion = _first_float(
        telemetry.get("spread_expansion_rate"),
        telemetry.get("spread_expansion_pct"),
    )
    latency_zscore = _first_float(
        telemetry.get("api_latency_zscore"),
        telemetry.get("latency_zscore"),
        _z_score(
            latency_ms,
            telemetry.get("api_latency_mean_5m"),
            telemetry.get("api_latency_std_5m"),
        ),
    )
    fill_zscore = _first_float(
        telemetry.get("fill_time_zscore"),
        _z_score(
            fill_ms,
            telemetry.get("avg_fill_time_mean_5m"),
            telemetry.get("avg_fill_time_std_5m"),
        ),
    )
    stress = 0.0
    reasons: list[str] = []
    if latency_ms is not None and latency_ms >= 750:
        stress += _clamp((latency_ms - 250.0) / 15.0)
        reasons.append(f"api_latency_ms={latency_ms:.0f}")
    if latency_zscore is not None and latency_zscore >= 2.5:
        stress += _clamp(latency_zscore * 18.0)
        reasons.append(f"api_latency_zscore={latency_zscore:.2f}")
    if fill_ms is not None and fill_ms >= 1500:
        stress += _clamp((fill_ms - 500.0) / 40.0)
        reasons.append(f"avg_fill_time_ms={fill_ms:.0f}")
    if fill_zscore is not None and fill_zscore >= 2.5:
        stress += _clamp(fill_zscore * 15.0)
        reasons.append(f"fill_time_zscore={fill_zscore:.2f}")
    if error_rate is not None and error_rate >= 0.03:
        stress += _clamp(error_rate * 600.0)
        reasons.append(f"api_error_rate={error_rate:.3f}")
    if spread_expansion is not None and spread_expansion >= 0.35:
        stress += _clamp(spread_expansion * 50.0)
        reasons.append(f"spread_expansion={spread_expansion:.3f}")
    return (
        {
            "present": bool(telemetry),
            "api_latency_ms": latency_ms,
            "api_latency_zscore": round(latency_zscore, 4) if latency_zscore is not None else None,
            "avg_fill_time_ms": fill_ms,
            "fill_time_zscore": round(fill_zscore, 4) if fill_zscore is not None else None,
            "api_error_rate": error_rate,
            "spread_expansion_rate": spread_expansion,
        },
        _clamp(stress),
        reasons,
    )


def evaluate_alternative_data_gate(
    *,
    account_state: dict[str, Any] | None,
    action: str,
) -> AlternativeDataGate:
    """Evaluate non-candle alternative data as a Level 0 model gate."""
    state = _dict(account_state)
    text, text_stress, text_reasons = _text_sentiment(state, action)
    liquidity, liquidity_stress, liquidity_reasons = _liquidity_footprints(state)
    intermarket, intermarket_stress, intermarket_reasons = _intermarket_effects(state, action)
    telemetry, telemetry_stress, telemetry_reasons = _hardware_telemetry(state)

    components = [
        text_stress,
        liquidity_stress,
        intermarket_stress,
        telemetry_stress,
    ]
    present_count = sum(
        1 for section in (text, liquidity, intermarket, telemetry) if section.get("present")
    )
    stress_score = max(components) if present_count else 0.0
    if sum(1 for value in components if value >= 45.0) >= 2:
        stress_score = min(100.0, stress_score + 15.0)

    if stress_score >= 70.0:
        decision = "veto"
        size_modifier = 0.0
    elif stress_score >= 45.0:
        decision = "size_down"
        size_modifier = 0.50
    elif stress_score >= 25.0:
        decision = "caution"
        size_modifier = 0.75
    else:
        decision = "pass"
        size_modifier = 1.0

    reasons = text_reasons + liquidity_reasons + intermarket_reasons + telemetry_reasons
    if not reasons:
        reasons = [
            "alternative data gate clear" if present_count else "no alternative data present"
        ]

    return AlternativeDataGate(
        version=ALTERNATIVE_DATA_GATE_VERSION,
        runtime_effect=ALTERNATIVE_DATA_GATE_RUNTIME_EFFECT,
        decision=decision,
        size_modifier=round(size_modifier, 4),
        stress_score=round(stress_score, 4),
        text_sentiment=text,
        liquidity_footprints=liquidity,
        intermarket_effects=intermarket,
        hardware_telemetry=telemetry,
        reasons=reasons[:12],
    )
