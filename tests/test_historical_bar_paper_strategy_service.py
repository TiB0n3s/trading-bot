#!/usr/bin/env python3
"""Tests for paper-only historical-bar ensemble strategy scoring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.historical_bar_paper_strategy_service import (  # noqa: E402
    HISTORICAL_BAR_PAPER_STRATEGY_RUNTIME_EFFECT,
    build_historical_bar_paper_strategy,
)


def _intelligence():
    return {
        "version": "historical_bar_model_intelligence_v1",
        "runtime_effect": "observe_only_no_live_authority",
        "authority": "observe_only_report_only_no_order_sizing_or_gate_authority",
        "status": "observe_only_ready",
        "labels": [
            {
                "label_target": "trend_scan_label",
                "model_id": "trend",
                "status": "observe_only_candidate_ready",
                "accuracy": 0.83,
                "positive_label_rate": 0.56,
                "negative_label_rate": 0.42,
            },
            {
                "label_target": "triple_barrier_label",
                "model_id": "triple",
                "status": "observe_only_candidate_ready",
                "accuracy": 0.75,
                "positive_label_rate": 0.52,
                "negative_label_rate": 0.47,
            },
        ],
    }


def test_paper_strategy_builds_master_confidence_and_paper_size():
    result = build_historical_bar_paper_strategy(
        symbol="AAPL",
        action="buy",
        context={"momentum_pct": 1.2},
        historical_bar_intelligence=_intelligence(),
        account_state={
            "bar_pattern_features": {
                "symbol": "AAPL",
                "bar_timestamp": "2026-06-04T15:00:00+00:00",
                "timeframe": "1Min",
                "atr_20_pct": 0.8,
                "rolling_volatility_20_pct": 0.9,
                "long_opportunity_score": 86,
                "pattern_score": 82,
                "volume_weighted_pressure_3": 1.1,
                "cvd_price_corr_20": 0.35,
                "vpin_toxicity_20": 0.15,
                "bid_ask_spread_pct": 0.04,
                "slippage_estimate_pct": 0.02,
                "liquidity_sweep_risk": 0.10,
                "rsi_14": 48,
                "ema_200": 100.0,
                "price_vs_ema_200_pct": 1.2,
                "macd": -0.12,
                "macd_signal": -0.16,
                "macd_histogram": 0.04,
                "macd_histogram_pct": 0.03,
                "macd_bullish_cross": 1,
                "macd_bearish_cross": 0,
                "macd_bearish_divergence": 0,
                "ema200_macd_reversal_signal": "long_reversal",
                "ema200_macd_reversal_score": 88,
                "price_vs_sma_20_pct": -0.3,
                "close_location": 0.72,
            },
            "portfolio_decision": {
                "duplicate_risk_score": 0.10,
                "overlap_symbols": [],
            },
        },
    ).to_dict()

    assert result["runtime_effect"] == HISTORICAL_BAR_PAPER_STRATEGY_RUNTIME_EFFECT
    assert result["authority"] == "paper_only_recommendation_no_live_order_sizing_or_gate_authority"
    assert result["status"] == "paper_ready"
    assert result["master_confidence_score"] >= 65
    assert result["paper_recommendation"] in {"paper_trade_candidate", "paper_size_candidate"}
    assert result["paper_position_size_pct"] > 0
    assert result["max_paper_risk_pct"] == 2.0
    assert result["model_weights"][0]["label_target"] == "trend_scan_label"
    assert result["baseline_delta"] is not None
    assert result["liquidity_stress_score"] is not None
    assert result["liquidity_stress_bucket"] in {"normal", "moderate"}
    assert result["feature_snapshot"]["ema200_macd_reversal_signal"] == "long_reversal"
    assert any("ema200_macd_reversal" in reason for reason in result["reasons"])
    assert result["guardrails"]["paper_only"] is True
    assert result["guardrails"]["can_block_live_trades"] is False
    assert result["guardrails"]["can_size_live_orders"] is False
    assert result["guardrails"]["can_submit_orders"] is False


def test_paper_strategy_stays_observe_when_models_are_not_ready():
    result = build_historical_bar_paper_strategy(
        symbol="AAPL",
        action="buy",
        context={},
        historical_bar_intelligence={
            "status": "not_ready",
            "labels": [
                {
                    "label_target": "trend_scan_label",
                    "status": "not_ready",
                    "accuracy": 0.40,
                }
            ],
        },
        account_state={},
    ).to_dict()

    assert result["status"] == "not_ready"
    assert result["master_confidence_score"] is None
    assert result["paper_recommendation"] == "paper_observe_only_no_model_score"
    assert result["paper_position_size_pct"] == 0.0


if __name__ == "__main__":
    test_paper_strategy_builds_master_confidence_and_paper_size()
    print("[OK] test_paper_strategy_builds_master_confidence_and_paper_size")
    test_paper_strategy_stays_observe_when_models_are_not_ready()
    print("[OK] test_paper_strategy_stays_observe_when_models_are_not_ready")
