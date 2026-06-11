"""Paper-only master strategy score from historical-bar model evidence.

This module bridges observe-only historical-bar candidates into a structured
paper-trading recommendation. It is deliberately non-authoritative: it does not
load model binaries, approve/reject trades, cap live sizing, or submit orders.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from typing import Any

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository
from services.historical_bar_model_intelligence_service import (
    build_historical_bar_model_intelligence,
)

HISTORICAL_BAR_PAPER_STRATEGY_VERSION = "historical_bar_paper_strategy_v1"
HISTORICAL_BAR_PAPER_STRATEGY_RUNTIME_EFFECT = "paper_only_recommendation_no_live_authority"


@dataclass(frozen=True)
class HistoricalBarPaperStrategy:
    version: str
    runtime_effect: str
    authority: str
    symbol: str | None
    action: str
    status: str
    master_confidence_score: float | None
    confidence_bucket: str
    paper_recommendation: str
    model_component_score: float | None
    current_feature_score: float | None
    naive_baseline_score: float | None
    baseline_delta: float | None
    weighted_model_accuracy: float | None
    impact_score: float | None
    liquidity_stress_score: float | None
    liquidity_stress_bucket: str
    volatility_adjustment: float | None
    paper_position_size_pct: float
    max_paper_risk_pct: float
    stop_risk_pct: float | None
    portfolio_correlation_penalty: float
    model_weights: list[dict[str, Any]]
    feature_snapshot: dict[str, Any]
    reasons: list[str]
    guardrails: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
    except Exception:
        return None
    if not math.isfinite(result):
        return None
    return result


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _latest_feature_snapshot(
    *,
    symbol: str | None,
    account_state: dict[str, Any],
    feature_repo: BarPatternFeatureRepository | None,
) -> dict[str, Any]:
    explicit = _dict(
        account_state.get("bar_pattern_features")
        or account_state.get("latest_bar_pattern_features")
        or account_state.get("historical_bar_features")
    )
    if explicit:
        return explicit
    if not symbol or feature_repo is None:
        return {}
    try:
        return feature_repo.latest_for_symbol(symbol) or {}
    except Exception:
        return {}


def _score_current_features(
    features: dict[str, Any], context: dict[str, Any]
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    candidates: list[float] = []
    long_score = _float(features.get("long_opportunity_score"))
    pattern_score = _float(features.get("pattern_score"))
    if long_score is not None:
        candidates.append(_clamp(long_score))
        reasons.append(f"long_opportunity_score={long_score:.1f}")
    if pattern_score is not None:
        candidates.append(_clamp(pattern_score))
        reasons.append(f"pattern_score={pattern_score:.1f}")

    pressure = _float(features.get("volume_weighted_pressure_3"))
    if pressure is not None:
        pressure_score = _clamp(50.0 + pressure * 10.0)
        candidates.append(pressure_score)
        reasons.append(f"volume_weighted_pressure_3={pressure:.3f}")

    cvd_corr = _float(features.get("cvd_price_corr_20"))
    if cvd_corr is not None:
        cvd_score = _clamp(50.0 + cvd_corr * 25.0)
        candidates.append(cvd_score)
        reasons.append(f"cvd_price_corr_20={cvd_corr:.3f}")

    vpin = _float(features.get("vpin_toxicity_20"))
    if vpin is not None:
        penalty = _clamp(vpin * 30.0, 0.0, 35.0)
        candidates.append(70.0 - penalty)
        reasons.append(f"vpin_toxicity_20={vpin:.3f}")

    reversal_score = _float(features.get("ema200_macd_reversal_score"))
    reversal_signal = str(features.get("ema200_macd_reversal_signal") or "none")
    if reversal_score is not None:
        candidates.append(_clamp(reversal_score))
        reasons.append(f"ema200_macd_reversal={reversal_signal}:{reversal_score:.1f}")

    if int(_float(features.get("macd_bearish_divergence")) or 0):
        candidates.append(35.0)
        reasons.append("macd_bearish_divergence=1")

    context_momentum = _float(context.get("momentum_pct"))
    if context_momentum is not None:
        candidates.append(_clamp(50.0 + context_momentum * 10.0))
        reasons.append(f"context_momentum_pct={context_momentum:.3f}")

    if not candidates:
        return 50.0, ["no_current_bar_features; neutral current score"]
    return round(sum(candidates) / len(candidates), 4), reasons


def _naive_baseline_score(features: dict[str, Any], context: dict[str, Any]) -> tuple[float, str]:
    rsi = _float(features.get("rsi_14"))
    price_vs_sma = _float(features.get("price_vs_sma_20_pct"))
    close_location = _float(features.get("close_location"))
    if rsi is None and price_vs_sma is None and close_location is None:
        momentum = _float(context.get("momentum_pct"))
        if momentum is None:
            return 50.0, "neutral_baseline_no_rsi_or_sma_context"
        return _clamp(50.0 + momentum * 8.0), "momentum_only_naive_baseline"

    score = 50.0
    if rsi is not None:
        if rsi <= 35:
            score += 12.0
        elif rsi >= 70:
            score -= 10.0
        else:
            score += (50.0 - abs(rsi - 50.0)) / 50.0 * 6.0
    if price_vs_sma is not None:
        if price_vs_sma < -1.0:
            score += 8.0
        elif price_vs_sma > 2.0:
            score -= 8.0
    if close_location is not None:
        score += (close_location - 0.5) * 10.0
    return round(_clamp(score), 4), "short_term_mean_reversion_baseline"


def _model_component(
    historical_bar_intelligence: dict[str, Any],
    *,
    action: str,
) -> tuple[float | None, float | None, list[dict[str, Any]], list[str]]:
    labels = historical_bar_intelligence.get("labels") or []
    weights: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_total = 0.0
    accuracy_sum = 0.0
    reasons: list[str] = []
    direction_key = "positive_label_rate" if action == "buy" else "negative_label_rate"
    for label in labels:
        if label.get("status") != "observe_only_candidate_ready":
            continue
        accuracy = _float(label.get("accuracy"))
        directional_rate = _float(label.get(direction_key))
        if accuracy is None:
            continue
        if directional_rate is None:
            directional_rate = 0.50
        # Accuracy is model quality; directional label rate is label prior.
        score = _clamp((accuracy * 100.0 * 0.65) + (directional_rate * 100.0 * 0.35))
        weight = max(0.01, accuracy - 0.50)
        weighted_sum += score * weight
        accuracy_sum += accuracy * weight
        weight_total += weight
        weights.append(
            {
                "label_target": label.get("label_target"),
                "model_id": label.get("model_id"),
                "accuracy": round(accuracy, 4),
                "directional_label_rate": round(directional_rate, 4),
                "score": round(score, 4),
                "weight": round(weight, 4),
            }
        )
    if not weights or weight_total <= 0:
        return None, None, [], ["no_ready_historical_bar_models"]
    weights.sort(key=lambda item: item["weight"], reverse=True)
    model_score = round(weighted_sum / weight_total, 4)
    weighted_accuracy = round(accuracy_sum / weight_total, 4)
    reasons.append(f"model_component_score={model_score:.2f}")
    return model_score, weighted_accuracy, weights, reasons


def _portfolio_correlation_penalty(account_state: dict[str, Any]) -> tuple[float, list[str]]:
    portfolio = _dict(account_state.get("portfolio_decision"))
    duplicate = _float(portfolio.get("duplicate_risk_score"))
    cluster_exposure = _float(portfolio.get("cluster_exposure_pct"))
    penalty = 0.0
    reasons: list[str] = []
    if duplicate is not None:
        penalty += _clamp(duplicate * 12.0, 0.0, 12.0)
        reasons.append(f"duplicate_risk_score={duplicate:.3f}")
    if cluster_exposure is not None and cluster_exposure > 25.0:
        penalty += _clamp((cluster_exposure - 25.0) / 5.0, 0.0, 10.0)
        reasons.append(f"cluster_exposure_pct={cluster_exposure:.2f}")
    overlap_symbols = portfolio.get("overlap_symbols") or []
    if overlap_symbols:
        penalty += min(5.0, len(overlap_symbols) * 1.5)
        reasons.append(f"overlap_symbols={len(overlap_symbols)}")
    return round(_clamp(penalty, 0.0, 20.0), 4), reasons


def _liquidity_stress(
    features: dict[str, Any],
    account_state: dict[str, Any],
) -> tuple[float, str, list[str]]:
    execution = _dict(account_state.get("execution_quality"))
    volatility = _dict(account_state.get("volatility_normalization"))
    components: list[float] = []
    reasons: list[str] = []

    vpin = _float(features.get("vpin_toxicity_20"))
    if vpin is not None:
        components.append(_clamp(vpin * 100.0))
        reasons.append(f"lsi_vpin={vpin:.3f}")

    spread = _float(features.get("bid_ask_spread_pct")) or _float(execution.get("spread_pct"))
    if spread is not None:
        components.append(_clamp(spread * 80.0))
        reasons.append(f"lsi_spread_pct={spread:.3f}")

    slippage = _float(features.get("slippage_estimate_pct")) or _float(
        execution.get("slippage_estimate_pct")
    )
    if slippage is not None:
        components.append(_clamp(slippage * 120.0))
        reasons.append(f"lsi_slippage_pct={slippage:.3f}")

    liquidity_sweep = _float(features.get("liquidity_sweep_risk"))
    if liquidity_sweep is not None:
        components.append(_clamp(liquidity_sweep * 100.0))
        reasons.append(f"lsi_liquidity_sweep={liquidity_sweep:.3f}")

    stretch = _float(volatility.get("move_zscore"))
    if stretch is not None:
        components.append(_clamp(abs(stretch) * 20.0))
        reasons.append(f"lsi_move_zscore={stretch:.3f}")

    if not components:
        return 0.0, "unknown", ["lsi_missing_inputs"]
    score = round(sum(components) / len(components), 4)
    if score >= 70:
        bucket = "severe"
    elif score >= 45:
        bucket = "elevated"
    elif score >= 20:
        bucket = "moderate"
    else:
        bucket = "normal"
    return score, bucket, reasons


def _paper_sizing(
    *,
    confidence: float,
    features: dict[str, Any],
    account_state: dict[str, Any],
) -> tuple[float, float | None, float | None, float, float, list[str]]:
    reasons: list[str] = []
    base_size_pct = _env_float("HISTORICAL_BAR_PAPER_BASE_SIZE_PCT", 2.0)
    max_size_pct = _env_float("HISTORICAL_BAR_PAPER_MAX_SIZE_PCT", 5.0)
    target_vol_pct = _env_float("HISTORICAL_BAR_PAPER_TARGET_VOL_PCT", 1.0)
    max_risk_pct = _env_float("HISTORICAL_BAR_PAPER_MAX_RISK_PCT", 2.0)
    stop_atr_mult = _env_float("HISTORICAL_BAR_PAPER_STOP_ATR_MULT", 1.5)

    atr_pct = (
        _float(features.get("atr_20_pct"))
        or _float(_dict(account_state.get("volatility_normalization")).get("atr_20_pct"))
        or _float(account_state.get("atr_20_pct"))
    )
    current_vol = (
        _float(features.get("rolling_volatility_20_pct"))
        or _float(
            _dict(account_state.get("volatility_normalization")).get("rolling_volatility_20_pct")
        )
        or atr_pct
    )
    volatility_adjustment = 1.0
    if current_vol and current_vol > 0:
        volatility_adjustment = _clamp(target_vol_pct / current_vol, 0.25, 1.50)
        reasons.append(f"volatility_adjustment={volatility_adjustment:.3f}")

    confidence_multiplier = _clamp((confidence - 50.0) / 35.0, 0.0, 1.25)
    proposed = base_size_pct * confidence_multiplier * volatility_adjustment

    stop_risk_pct = stop_atr_mult * atr_pct if atr_pct and atr_pct > 0 else None
    if stop_risk_pct and stop_risk_pct > 0:
        risk_limited_size = max_risk_pct / stop_risk_pct * 100.0
        proposed = min(proposed, risk_limited_size)
        reasons.append(f"risk_limited_size_pct={risk_limited_size:.3f}")

    final_size = round(_clamp(proposed, 0.0, max_size_pct), 4)
    impact_score = _clamp((confidence * 0.75) + ((atr_pct or 0.0) * 12.5), 0.0, 100.0)
    return (
        final_size,
        round(stop_risk_pct, 4) if stop_risk_pct is not None else None,
        round(volatility_adjustment, 4),
        round(impact_score, 4),
        max_risk_pct,
        reasons,
    )


def build_historical_bar_paper_strategy(
    *,
    symbol: str | None,
    action: str | None,
    context: dict[str, Any] | None = None,
    account_state: dict[str, Any] | None = None,
    historical_bar_intelligence: dict[str, Any] | None = None,
    feature_repo: BarPatternFeatureRepository | None = None,
) -> HistoricalBarPaperStrategy:
    context = _dict(context)
    account_state = _dict(account_state)
    action = str(action or context.get("action") or account_state.get("action") or "buy").lower()
    reasons: list[str] = []
    intelligence = (
        historical_bar_intelligence
        or _dict(account_state.get("historical_bar_model_intelligence"))
        or build_historical_bar_model_intelligence()
    )
    features = _latest_feature_snapshot(
        symbol=symbol,
        account_state=account_state,
        feature_repo=feature_repo,
    )

    model_score, weighted_accuracy, model_weights, model_reasons = _model_component(
        intelligence,
        action=action,
    )
    reasons.extend(model_reasons)
    current_score, current_reasons = _score_current_features(features, context)
    reasons.extend(current_reasons)
    baseline_score, baseline_reason = _naive_baseline_score(features, context)
    reasons.append(baseline_reason)
    correlation_penalty, correlation_reasons = _portfolio_correlation_penalty(account_state)
    reasons.extend(correlation_reasons)
    liquidity_stress_score, liquidity_stress_bucket, liquidity_reasons = _liquidity_stress(
        features,
        account_state,
    )
    reasons.extend(liquidity_reasons)
    liquidity_penalty = _clamp(liquidity_stress_score / 6.0, 0.0, 15.0)

    if model_score is None:
        master = None
        baseline_delta = None
        status = "not_ready"
        recommendation = "paper_observe_only_no_model_score"
        bucket = "unscored"
        size_pct = 0.0
        stop_risk_pct = None
        volatility_adjustment = None
        impact_score = None
        max_risk_pct = _env_float("HISTORICAL_BAR_PAPER_MAX_RISK_PCT", 2.0)
    else:
        master = _clamp(
            (model_score * 0.55)
            + (current_score * 0.35)
            + (baseline_score * 0.10)
            - correlation_penalty
            - liquidity_penalty
        )
        baseline_delta = round(master - baseline_score, 4)
        if master >= 75:
            bucket = "high"
            recommendation = "paper_size_candidate"
        elif master >= 65:
            bucket = "medium"
            recommendation = "paper_trade_candidate"
        elif master >= 55:
            bucket = "low"
            recommendation = "paper_watch"
        else:
            bucket = "very_low"
            recommendation = "paper_avoid"
        status = "paper_ready"
        (
            size_pct,
            stop_risk_pct,
            volatility_adjustment,
            impact_score,
            max_risk_pct,
            sizing_reasons,
        ) = _paper_sizing(
            confidence=master,
            features=features,
            account_state=account_state,
        )
        reasons.extend(sizing_reasons)
        if recommendation in {"paper_watch", "paper_avoid"}:
            size_pct = 0.0

    snapshot = {
        key: features.get(key)
        for key in (
            "symbol",
            "bar_timestamp",
            "timeframe",
            "close",
            "atr_20_pct",
            "rolling_volatility_20_pct",
            "long_opportunity_score",
            "pattern_score",
            "vpin_toxicity_20",
            "cvd_price_corr_20",
            "rsi_14",
            "ema_200",
            "price_vs_ema_200_pct",
            "macd",
            "macd_signal",
            "macd_histogram",
            "macd_histogram_pct",
            "macd_bullish_cross",
            "macd_bearish_cross",
            "macd_bearish_divergence",
            "ema200_macd_reversal_signal",
            "ema200_macd_reversal_score",
            "price_vs_sma_20_pct",
        )
        if features.get(key) is not None
    }
    return HistoricalBarPaperStrategy(
        version=HISTORICAL_BAR_PAPER_STRATEGY_VERSION,
        runtime_effect=HISTORICAL_BAR_PAPER_STRATEGY_RUNTIME_EFFECT,
        authority="paper_only_recommendation_no_live_order_sizing_or_gate_authority",
        symbol=symbol,
        action=action,
        status=status,
        master_confidence_score=round(master, 4) if master is not None else None,
        confidence_bucket=bucket,
        paper_recommendation=recommendation,
        model_component_score=model_score,
        current_feature_score=current_score,
        naive_baseline_score=baseline_score,
        baseline_delta=baseline_delta,
        weighted_model_accuracy=weighted_accuracy,
        impact_score=impact_score,
        liquidity_stress_score=liquidity_stress_score,
        liquidity_stress_bucket=liquidity_stress_bucket,
        volatility_adjustment=volatility_adjustment,
        paper_position_size_pct=size_pct,
        max_paper_risk_pct=max_risk_pct,
        stop_risk_pct=stop_risk_pct,
        portfolio_correlation_penalty=correlation_penalty,
        model_weights=model_weights,
        feature_snapshot=snapshot,
        reasons=reasons[:20],
        guardrails={
            "paper_only": True,
            "loads_model_binaries": False,
            "can_block_live_trades": False,
            "can_size_live_orders": False,
            "can_submit_orders": False,
            "requires_holdout_validation_before_authority": True,
        },
    )
