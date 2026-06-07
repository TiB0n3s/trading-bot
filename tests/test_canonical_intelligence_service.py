#!/usr/bin/env python3
"""Tests for canonical intelligence snapshot construction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.canonical_intelligence_service import (
    CANONICAL_INTELLIGENCE_VERSION,
    CANONICAL_INTELLIGENCE_MAX_JSON_BYTES,
    CANONICAL_INTELLIGENCE_REQUIRED_SECTIONS,
    build_canonical_intelligence_snapshot,
    canonical_json_size_bytes,
    validate_canonical_snapshot_contract,
)


def _snapshot(**overrides):
    args = {
        "symbol": "AAPL",
        "decision_ts": "2026-05-31T14:30:00+00:00",
        "action": "buy",
        "feature_semantic_version": "decision_snapshot_features_v2",
        "market_context_metadata": {
            "market_context_mtime": "2026-05-31T14:00:00+00:00",
        },
        "context": {
            "macro_regime": "risk_on",
            "market_bias": "buy",
            "trend_direction": "bullish",
            "trend_strength": "confirmed",
            "momentum_direction": "rising",
            "momentum_pct": 0.25,
            "momentum_state": "accelerating",
            "volume_state": "surge",
            "session_trend_label": "strong_uptrend",
            "session_trend_score": 4,
            "tape_bar_age_seconds": 12.5,
        },
        "account_state": {
            "session_momentum": {"updated_at": "2026-05-31T14:29:00+00:00"},
            "prediction_gate": {
                "ml_prediction_score": 62,
                "ml_prediction_bucket": "high_55_plus",
                "ml_prediction_confidence": "medium",
                "ml_prediction_sample_size": 31,
            },
            "setup_observation": {
                "setup_label": "near_vwap_recovery",
                "setup_policy_action": "boost",
                "setup_score": 72,
            },
            "setup_quality": {
                "source": "setup_engine",
                "recommendation": "favorable",
                "key": "bullish/confirmed|near_vwap|neutral",
                "structure": {
                    "structure_state": "high_quality_structure",
                    "base_quality": "clean_base",
                    "failed_breakout_risk": "low",
                    "compression_expansion_state": "compression_into_expansion",
                    "htf_location_state": "room_to_supply",
                    "anchored_vwap_state": "near_anchored_vwap",
                    "gap_context_state": "gap_accepted",
                    "retest_quality": "constructive_retest",
                    "reward_risk_state": "favorable_rr",
                    "structure_score": 0.88,
                },
            },
            "strategy_observation": {
                "trader_brain": {
                    "score": 81,
                    "setup_type": "continuation",
                    "approved_by_scorer": True,
                }
            },
            "buy_opportunity": {
                "buy_opportunity_score": 66,
                "buy_opportunity_recommendation": "buy_candidate",
            },
            "event_context": {
                "available": True,
                "event_signal": "constructive_watch",
                "authority": "context_only_no_standalone_buy_authority",
                "event_count": 3,
                "source_count": 2,
                "trusted_source_count": 2,
                "confidence_cap": "two_independent_reputable_sources",
                "source_tiers": ["confirmed_financial_news", "deep_analysis"],
                "catalyst_score": 72,
                "consumer_appetite_score": 70,
                "revenue_impact_score": 68,
                "profit_potential_score": 66,
                "margin_risk_score": 20,
            },
            "ml_outcome": {
                "advisory_decision": "avoid",
                "authority_mode": "observe_only_compare",
                "enforced": False,
                "effect_on_size": "none",
                "reason": "negative compare ignored by design",
            },
            "decision_policy": {
                "utility_estimate": {
                    "utility_decision": "trade_candidate",
                    "expected_value_pct": 0.22,
                    "portfolio_adjusted_utility_pct": 0.22,
                },
            },
            "calibrated_confidence": {
                "primary_source": "setup_quality",
                "primary_predicted_win_rate": 0.6,
                "primary_realized_win_rate": 0.64,
                "primary_sample_size": 28,
                "confidence_quality": "medium",
                "sources": {
                    "setup_quality": {
                        "realized_win_rate": 0.64,
                        "calibration_error": 0.04,
                    },
                },
            },
            "market_regime": {
                "composite_regime": "trend_expansion",
                "trend_regime": "trend_continuation",
                "volatility_regime": "high_volatility_expansion",
                "event_regime": "gap_or_news_follow_through",
                "sector_rotation_regime": "broad_participation",
                "liquidity_regime": "normal",
                "confidence": "medium",
                "strategy_weights": {
                    "trend_continuation": 1.4,
                    "orderly_pullback": 1.15,
                    "mean_reversion": 0.75,
                    "momentum_chase": 1.1,
                },
            },
            "market_microstructure": {
                "session_phase": "first_30m",
                "opening_range_state": "above_opening_range",
                "gap_state": "gap_up_accepted",
                "vwap_state": "above_vwap",
                "liquidity_state": "volume_expansion",
                "intraday_volatility_state": "range_expansion",
                "compression_state": "directional_bars",
                "auction_quality": "clean_auction",
                "breakout_quality": "confirmed_expansion_breakout",
                "reversion_risk": "normal",
                "microstructure_score": 0.82,
                "expectancy_modifier": 1.12,
            },
            "market_participation": {
                "participation_state": "confirmed",
                "sector_relative_strength_state": "supportive",
                "peer_confirmation_state": "supportive",
                "breadth_state": "supportive",
                "index_participation_state": "supportive",
                "leader_laggard_state": "leader_confirmed",
                "relative_volume_state": "confirming_relative_volume",
                "confirmation_score": 0.86,
                "isolated_move_risk": "low",
                "expectancy_modifier": 1.16,
            },
            "volatility_normalization": {
                "stretch_state": "stretched",
                "entry_distance_atr": 1.35,
                "move_zscore": 1.6,
                "range_percentile": 82,
                "gap_percentile": 74,
                "spread_atr_pct": 0.09,
                "stop_excursion_ratio": 1.1,
                "volatility_regime": "normal",
                "chase_risk": "elevated",
                "stop_quality": "aligned_with_excursion",
                "volatility_adjusted_score": 0.58,
                "expectancy_modifier": 0.96,
            },
            "downside_asymmetry": {
                "downside_state": "asymmetric_downside_elevated",
                "gap_down_vulnerability": "elevated",
                "catalyst_risk": "near_earnings",
                "overnight_risk": "none",
                "headline_sensitivity": "elevated",
                "beta_shock_sensitivity": "elevated_beta",
                "historical_mae_state": "elevated_historical_mae",
                "failure_signature": "failed_breakout_vwap_loss",
                "downside_score": 0.52,
                "expected_adverse_modifier": 1.22,
            },
            "exit_decision_quality": {
                "exit_pressure_state": "moderate_exit_pressure",
                "exit_quality_score": 0.55,
                "recommended_action": "tighten_or_partial",
            },
            "portfolio_decision": {
                "decision": "size_down",
                "size_multiplier": 0.75,
                "duplicate_risk_score": 0.48,
                "incremental_var_pct": 1.35,
                "beta_contribution_delta": 1.2,
                "crowded_theme": "ai_infra",
                "overlap_symbols": ["NVDA", "AMD"],
            },
            "execution_quality": {
                "decision": "size_down",
                "fill_quality": "degraded",
                "spread_pct": 0.42,
                "slippage_estimate_pct": 0.22,
                "signal_executable_gap_pct": 0.18,
                "quote_instability_score": 0.25,
                "net_execution_cost_pct": 0.44,
            },
            "regime_observation": {
                "regime_id": 0,
                "regime_label": "quiet_bull",
                "confidence": "medium",
                "stable": True,
                "runtime_effect": "observe_only_no_order_authority",
            },
            "regime_routing_decision": {
                "active_model_slot": "regime_0_model",
                "sub_model_strategy": "random_forest_trend_continuation",
                "size_modifier": 1.0,
                "allow_new_longs": True,
                "runtime_effect": "observe_only_no_order_authority",
            },
            "regime_observation_context": {
                "regime_observation_source": "deterministic_fallback",
            },
            "rollout_contract": {
                "report_version": "rollout_contract_v1",
                "runtime_effect": "telemetry_only_no_live_authority",
                "assessments": [
                    {
                        "feature_family": "execution_quality",
                        "status": "size_down_candidate",
                        "review_window_start": "2026-05-30",
                        "review_window_end": "2026-05-31",
                        "restrictions": {"allowed_actions": ["size_down_only"]},
                    }
                ],
            },
            "historical_bar_model_intelligence": {
                "version": "historical_bar_model_intelligence_v1",
                "runtime_effect": "observe_only_no_live_authority",
                "authority": "observe_only_report_only_no_order_sizing_or_gate_authority",
                "status": "observe_only_ready",
                "diagnostics_found": 10,
                "labels_assessed": 2,
                "ready_label_count": 2,
                "label_targets": ["trend_scan_label", "triple_barrier_label"],
                "latest_generated_at": "2026-06-07T13:22:37+00:00",
                "accuracy_min": 0.7556,
                "accuracy_max": 0.8308,
                "labels": [
                    {
                        "label_target": "trend_scan_label",
                        "model_id": "historical_bar_trend_scan_label_20260607T132237Z",
                        "status": "observe_only_candidate_ready",
                        "rows_loaded": 14750,
                        "symbol_count": 59,
                        "accuracy": 0.8308,
                        "positive_label_rate": 0.5263,
                        "negative_label_rate": 0.4521,
                        "failed_thresholds": [],
                    },
                    {
                        "label_target": "triple_barrier_label",
                        "model_id": "historical_bar_triple_barrier_label_20260607T132203Z",
                        "status": "observe_only_candidate_ready",
                        "rows_loaded": 14750,
                        "symbol_count": 59,
                        "accuracy": 0.7556,
                        "positive_label_rate": 0.4406,
                        "negative_label_rate": 0.5536,
                        "failed_thresholds": [],
                    },
                ],
                "guardrails": {
                    "loads_model_binaries": False,
                    "can_block_trades": False,
                    "can_size_orders": False,
                    "can_submit_orders": False,
                    "requires_explicit_authority_wiring_for_runtime_use": True,
                },
            },
            "historical_bar_paper_strategy": {
                "version": "historical_bar_paper_strategy_v1",
                "runtime_effect": "paper_only_recommendation_no_live_authority",
                "authority": "paper_only_recommendation_no_live_order_sizing_or_gate_authority",
                "status": "paper_ready",
                "master_confidence_score": 72.5,
                "confidence_bucket": "medium",
                "paper_recommendation": "paper_trade_candidate",
                "model_component_score": 70.1,
                "current_feature_score": 78.2,
                "naive_baseline_score": 54.0,
                "baseline_delta": 18.5,
                "weighted_model_accuracy": 0.80,
                "impact_score": 68.0,
                "volatility_adjustment": 1.1,
                "paper_position_size_pct": 1.25,
                "max_paper_risk_pct": 2.0,
                "stop_risk_pct": 1.2,
                "portfolio_correlation_penalty": 1.0,
                "model_weights": [],
                "feature_snapshot": {
                    "symbol": "AAPL",
                    "bar_timestamp": "2026-06-04T15:00:00+00:00",
                },
                "reasons": ["model_component_score=70.10"],
                "guardrails": {
                    "paper_only": True,
                    "loads_model_binaries": False,
                    "can_block_live_trades": False,
                    "can_size_live_orders": False,
                    "can_submit_orders": False,
                    "requires_holdout_validation_before_authority": True,
                },
            },
            "paper_learning_authority_override": {
                "allowed": True,
                "setup_score": 82,
                "buy_opportunity_score": 9.5,
                "position_size_pct": 0.5,
                "reason": "paper learning authority approved strong canonical intelligence",
            },
            "intelligence_context": {
                "summary": {
                    "support_count": 3,
                    "risk_count": 1,
                }
            },
            "policy_artifacts": {"state_hash": "abc"},
        },
    }
    args.update(overrides)
    return build_canonical_intelligence_snapshot(**args)


def test_build_canonical_snapshot_collects_core_state_and_hashes():
    snapshot = _snapshot()

    data = snapshot.to_dict()
    assert data["version"] == CANONICAL_INTELLIGENCE_VERSION
    assert data["symbol"] == "AAPL"
    assert data["regime_state"]["macro_regime"] == "risk_on"
    assert data["regime_state"]["inferred_regime_id"] == 0
    assert data["regime_state"]["inferred_regime_label"] == "quiet_bull"
    assert data["regime_state"]["inferred_regime_source"] == "deterministic_fallback"
    assert data["regime_state"]["regime_model_slot"] == "regime_0_model"
    assert data["regime_state"]["regime_sub_model_strategy"] == "random_forest_trend_continuation"
    assert data["regime_state"]["market_regime"] == "trend_expansion"
    assert data["regime_state"]["trend_regime"] == "trend_continuation"
    assert data["regime_state"]["volatility_regime"] == "high_volatility_expansion"
    assert data["regime_state"]["strategy_weights"]["trend_continuation"] == 1.4
    assert data["regime_state"]["session_phase"] == "first_30m"
    assert data["regime_state"]["breakout_quality"] == "confirmed_expansion_breakout"
    assert data["regime_state"]["microstructure_score"] == 0.82
    assert data["regime_state"]["microstructure_expectancy_modifier"] == 1.12
    assert data["regime_state"]["participation_state"] == "confirmed"
    assert data["regime_state"]["peer_confirmation_state"] == "supportive"
    assert data["regime_state"]["participation_confirmation_score"] == 0.86
    assert data["regime_state"]["isolated_move_risk"] == "low"
    assert data["regime_state"]["volatility_stretch_state"] == "stretched"
    assert data["regime_state"]["entry_distance_atr"] == 1.35
    assert data["regime_state"]["move_zscore"] == 1.6
    assert data["regime_state"]["volatility_chase_risk"] == "elevated"
    assert data["regime_state"]["stop_quality"] == "aligned_with_excursion"
    assert data["regime_state"]["portfolio_decision"] == "size_down"
    assert data["regime_state"]["portfolio_duplicate_risk_score"] == 0.48
    assert data["regime_state"]["crowded_theme"] == "ai_infra"
    assert data["regime_state"]["execution_quality_decision"] == "size_down"
    assert data["regime_state"]["fill_quality"] == "degraded"
    assert data["regime_state"]["spread_bucket"] == "wide"
    assert data["regime_state"]["net_execution_cost_pct"] == 0.44
    assert data["trend_state"]["direction"] == "bullish"
    assert data["momentum_state"]["session_label"] == "strong_uptrend"
    assert data["event_state"]["event_signal"] == "constructive_watch"
    assert data["event_state"]["confidence_cap"] == "two_independent_reputable_sources"
    assert data["event_state"]["trusted_source_count"] == 2
    assert data["event_state"]["catalyst_score"] == 72
    assert data["prediction_state"]["ml_score"] == 62
    assert data["pattern_state"]["runtime_effect"] == "observe_only_no_live_authority"
    assert data["pattern_state"]["authority"] == "observe_only_no_live_authority"
    assert data["pattern_state"]["pattern_label"] == "trend_continuation_with_participation"
    assert data["pattern_state"]["directional_bias"] == "constructive"
    assert data["pattern_state"]["favorable_move_probability"] == 0.56
    assert data["pattern_state"]["expected_mfe_pct"] == 0.85
    assert data["pattern_state"]["expected_mae_pct"] == -0.45
    assert data["pattern_state"]["historical_status"] == "needs_lifecycle_outcomes"
    assert data["pattern_state"]["prediction_status"] == "observe_only"
    assert data["pattern_state"]["historical_bar_model_status"] == "observe_only_ready"
    assert data["pattern_state"]["historical_bar_ready_label_count"] == 2
    assert data["pattern_state"]["historical_bar_label_targets"] == [
        "trend_scan_label",
        "triple_barrier_label",
    ]
    assert data["pattern_state"]["historical_bar_runtime_effect"] == "observe_only_no_live_authority"
    assert data["pattern_state"]["historical_bar_master_confidence_score"] == 72.5
    assert data["pattern_state"]["historical_bar_confidence_bucket"] == "medium"
    assert data["pattern_state"]["historical_bar_paper_recommendation"] == "paper_trade_candidate"
    assert data["pattern_state"]["historical_bar_paper_position_size_pct"] == 1.25
    assert data["pattern_state"]["historical_bar_baseline_delta"] == 18.5
    assert (
        data["pattern_state"]["historical_bar_paper_runtime_effect"]
        == "paper_only_recommendation_no_live_authority"
    )
    assert data["setup_state"]["policy_action"] == "boost"
    assert data["setup_state"]["quality_source"] == "setup_engine"
    assert data["setup_state"]["quality_recommendation"] == "favorable"
    assert data["setup_state"]["structure_state"] == "high_quality_structure"
    assert data["setup_state"]["reward_risk_state"] == "favorable_rr"
    assert data["strategy_state"]["trader_brain_score"] == 81
    assert data["opportunity_state"]["recommendation"] == "buy_candidate"
    assert data["advisory_authority_state"]["ml_outcome"]["authority_mode"] == "observe_only_compare"
    assert (
        data["advisory_authority_state"]["utility_estimate"]["utility_decision"]
        == "trade_candidate"
    )
    assert data["advisory_authority_state"]["portfolio_decision"]["decision"] == "size_down"
    assert data["advisory_authority_state"]["execution_quality"]["decision"] == "size_down"
    assert data["advisory_authority_state"]["regime_observation"]["regime_label"] == "quiet_bull"
    assert data["advisory_authority_state"]["regime_routing_decision"]["active_model_slot"] == "regime_0_model"
    assert (
        data["advisory_authority_state"]["market_microstructure"]["session_phase"]
        == "first_30m"
    )
    assert (
        data["advisory_authority_state"]["market_participation"][
            "participation_state"
        ]
        == "confirmed"
    )
    assert (
        data["advisory_authority_state"]["volatility_normalization"]["chase_risk"]
        == "elevated"
    )
    assert data["advisory_authority_state"]["downside_asymmetry"]["downside_score"] == 0.52
    assert (
        data["advisory_authority_state"]["exit_decision_quality"][
            "recommended_action"
        ]
        == "tighten_or_partial"
    )
    rollout = data["advisory_authority_state"]["rollout_contract"]
    assert rollout["report_version"] == "rollout_contract_v1"
    assert rollout["assessments"][0]["feature_family"] == "execution_quality"
    assert rollout["assessments"][0]["status"] == "size_down_candidate"
    assert (
        data["advisory_authority_state"]["paper_learning_authority_outcome"][
            "allowed"
        ]
        is True
    )
    assert (
        data["advisory_authority_state"]["paper_learning_authority_outcome"][
            "setup_score"
        ]
        == 82
    )
    assert data["confidence"]["raw_confidence_labels"]["prediction_confidence"] == "medium"
    assert data["confidence"]["primary_source"] == "setup_quality"
    assert data["confidence"]["primary_realized_win_rate"] == 0.64
    assert data["confidence"]["confidence_quality"] == "medium"
    assert data["event_state"]["support_count"] == 3
    assert data["analytics_state"]["runtime_effect"] == "canonical_audit_and_ml_context_only"
    assert data["analytics_state"]["families"]["historical_bar_ml"]["status"] == "active"
    assert data["analytics_state"]["families"]["paper_strategy_ensemble"]["status"] == "active"
    assert (
        data["analytics_state"]["families"]["historical_bar_ml"]["authority"]
        == "observe_only_report_only_no_order_sizing_or_gate_authority"
    )
    assert data["analytics_state"]["model_router"]["current_regime_label"] == "quiet_bull"
    assert data["analytics_state"]["model_router"]["active_model_slot"] == "regime_0_model"
    ai_pattern = data["analytics_state"]["ai_momentum_pattern"]
    assert ai_pattern["runtime_effect"] == "observe_only_no_live_authority"
    assert ai_pattern["pattern_label"] == "trend_continuation_with_participation"
    assert ai_pattern["directional_bias"] == "constructive"
    assert ai_pattern["expected_horizon"] == "15m_to_60m"
    assert ai_pattern["favorable_move_probability"] == 0.56
    assert ai_pattern["historical_status"] == "needs_lifecycle_outcomes"
    assert ai_pattern["prediction_layer"]["status"] == "observe_only"
    ai_review = data["analytics_state"]["ai_review_suite"]
    assert ai_review["r"] == "observe_only_no_live_authority"
    assert ai_review["n"] == 10
    historical_bar = data["analytics_state"]["historical_bar_model_intelligence"]
    assert historical_bar["status"] == "observe_only_ready"
    assert historical_bar["ready_label_count"] == 2
    assert (
        data["analytics_state"]["families"]["historical_bar_ml"]["authority"]
        == "observe_only_report_only_no_order_sizing_or_gate_authority"
    )
    assert historical_bar["label_targets"] == ["trend_scan_label", "triple_barrier_label"]
    paper_strategy = data["analytics_state"]["historical_bar_paper_strategy"]
    assert paper_strategy["paper_recommendation"] == "paper_trade_candidate"
    assert paper_strategy["baseline_delta"] == 18.5
    assert (
        data["analytics_state"]["families"]["paper_strategy_ensemble"]["authority"]
        == "paper_only_recommendation_no_live_order_sizing_or_gate_authority"
    )
    assert "predictive" in data["analytics_state"]["active_families"]
    assert "historical_bar_ml" in data["analytics_state"]["active_families"]
    assert "sentiment_nlp" in data["analytics_state"]["active_families"]
    assert data["analytics_state"]["families"]["alternative_data"]["status"] == "not_integrated"
    assert data["policy_artifact_ref"]["state_hash"] == "abc"
    assert data["freshness_sec"]["market_context"] == 1800.0
    assert data["freshness_sec"]["session_momentum"] == 60.0
    assert len(data["feature_vector_hash"]) == 64


def test_canonical_snapshot_contract_requires_sections_and_size_limit():
    snapshot = _snapshot()
    result = validate_canonical_snapshot_contract(snapshot)

    assert result["ok"] is True
    assert result["missing_sections"] == []
    assert result["json_size_bytes"] <= CANONICAL_INTELLIGENCE_MAX_JSON_BYTES
    for section in CANONICAL_INTELLIGENCE_REQUIRED_SECTIONS:
        assert section in snapshot.to_dict()


def test_canonical_hash_is_stable_for_dict_insertion_order():
    first = _snapshot(
        context={
            "macro_regime": "risk_on",
            "market_bias": "buy",
            "trend_direction": "bullish",
            "trend_strength": "confirmed",
            "momentum_pct": 0.25,
        },
        account_state={
            "prediction_gate": {
                "ml_prediction_score": 62,
                "ml_prediction_bucket": "high_55_plus",
            },
            "setup_observation": {
                "setup_label": "near_vwap_recovery",
                "setup_policy_action": "boost",
            },
        },
    )
    second = _snapshot(
        context={
            "momentum_pct": 0.25,
            "trend_strength": "confirmed",
            "trend_direction": "bullish",
            "market_bias": "buy",
            "macro_regime": "risk_on",
        },
        account_state={
            "setup_observation": {
                "setup_policy_action": "boost",
                "setup_label": "near_vwap_recovery",
            },
            "prediction_gate": {
                "ml_prediction_bucket": "high_55_plus",
                "ml_prediction_score": 62,
            },
        },
    )

    assert first.feature_vector_hash == second.feature_vector_hash


def test_canonical_hash_normalizes_float_formatting():
    first = _snapshot(context={"momentum_pct": 0.1 + 0.2})
    second = _snapshot(context={"momentum_pct": 0.3})

    assert first.feature_vector_hash == second.feature_vector_hash


def test_canonical_hash_normalizes_scalar_list_order_for_set_like_fields():
    first = _snapshot(
        account_state={
            "event_context": {
                "source_tiers": ["deep_analysis", "confirmed_financial_news"],
            },
            "portfolio_decision": {
                "overlap_symbols": ["NVDA", "AMD"],
            },
        }
    )
    second = _snapshot(
        account_state={
            "event_context": {
                "source_tiers": ["confirmed_financial_news", "deep_analysis"],
            },
            "portfolio_decision": {
                "overlap_symbols": ["AMD", "NVDA"],
            },
        }
    )

    assert first.feature_vector_hash == second.feature_vector_hash


def test_canonical_snapshot_distinguishes_absent_null_and_empty_list_semantics():
    absent = _snapshot(account_state={"intelligence_context": {"summary": {}}})
    explicit_null = _snapshot(
        account_state={
            "intelligence_context": {
                "summary": {
                    "primary_supports": None,
                    "primary_risks": None,
                }
            }
        }
    )
    empty_list = _snapshot(
        account_state={
            "intelligence_context": {
                "summary": {
                    "primary_supports": [],
                    "primary_risks": [],
                }
            }
        }
    )

    # Absent and explicit null are equivalent because the canonical schema
    # materializes all known fields as null. Empty lists are meaningful.
    assert absent.feature_vector_hash == explicit_null.feature_vector_hash
    assert absent.feature_vector_hash != empty_list.feature_vector_hash


def test_canonical_snapshot_stays_below_size_limit():
    snapshot = _snapshot()
    assert canonical_json_size_bytes(snapshot) < CANONICAL_INTELLIGENCE_MAX_JSON_BYTES


def main():
    tests = [
        test_build_canonical_snapshot_collects_core_state_and_hashes,
        test_canonical_snapshot_contract_requires_sections_and_size_limit,
        test_canonical_hash_is_stable_for_dict_insertion_order,
        test_canonical_hash_normalizes_float_formatting,
        test_canonical_hash_normalizes_scalar_list_order_for_set_like_fields,
        test_canonical_snapshot_distinguishes_absent_null_and_empty_list_semantics,
        test_canonical_snapshot_stays_below_size_limit,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} canonical intelligence tests passed.")


if __name__ == "__main__":
    main()
