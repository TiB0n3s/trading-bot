"""Operator report for paper-only historical-bar ensemble strategy scoring."""

from __future__ import annotations

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository
from services.historical_bar_model_intelligence_service import (
    build_historical_bar_model_intelligence,
)
from services.historical_bar_paper_strategy_service import (
    build_historical_bar_paper_strategy,
)

HISTORICAL_BAR_PAPER_STRATEGY_REPORT_VERSION = "historical_bar_paper_strategy_report_v1"


def run_historical_bar_paper_strategy_report(
    *,
    symbol: str,
    action: str = "buy",
) -> bool:
    intelligence = build_historical_bar_model_intelligence()
    strategy = build_historical_bar_paper_strategy(
        symbol=symbol.upper(),
        action=action,
        context={"action": action},
        account_state={},
        historical_bar_intelligence=intelligence,
        feature_repo=BarPatternFeatureRepository(),
    ).to_dict()

    print()
    print("=" * 72)
    print("  Historical Bar Paper Strategy")
    print("=" * 72)
    print(f"report_version          : {HISTORICAL_BAR_PAPER_STRATEGY_REPORT_VERSION}")
    print(f"runtime_effect          : {strategy['runtime_effect']}")
    print(f"authority               : {strategy['authority']}")
    print(f"symbol                  : {strategy['symbol']}")
    print(f"action                  : {strategy['action']}")
    print(f"status                  : {strategy['status']}")
    print(f"master_confidence_score : {strategy['master_confidence_score']}")
    print(f"confidence_bucket       : {strategy['confidence_bucket']}")
    print(f"paper_recommendation    : {strategy['paper_recommendation']}")
    print(f"paper_position_size_pct : {strategy['paper_position_size_pct']}")
    print(f"max_paper_risk_pct      : {strategy['max_paper_risk_pct']}")
    print(f"stop_risk_pct           : {strategy['stop_risk_pct']}")
    print(f"impact_score            : {strategy['impact_score']}")
    print(f"liquidity_stress_score  : {strategy['liquidity_stress_score']}")
    print(f"liquidity_stress_bucket : {strategy['liquidity_stress_bucket']}")
    print(f"model_component_score   : {strategy['model_component_score']}")
    print(f"current_feature_score   : {strategy['current_feature_score']}")
    print(f"naive_baseline_score    : {strategy['naive_baseline_score']}")
    print(f"baseline_delta          : {strategy['baseline_delta']}")
    print(f"correlation_penalty     : {strategy['portfolio_correlation_penalty']}")

    print()
    print("Model weights")
    if strategy["model_weights"]:
        for item in strategy["model_weights"]:
            print(
                f"  {item['label_target']:<22} weight={item['weight']:<7} "
                f"accuracy={item['accuracy']:<7} score={item['score']:<7} "
                f"directional_rate={item['directional_label_rate']}"
            )
    else:
        print("  none")

    print()
    print("Latest feature snapshot")
    if strategy["feature_snapshot"]:
        for key, value in strategy["feature_snapshot"].items():
            print(f"  {key:<28}: {value}")
    else:
        print("  none")

    print()
    print("Reasons")
    for reason in strategy["reasons"][:12]:
        print(f"  - {reason}")

    print()
    print("Guardrails")
    for key, value in strategy["guardrails"].items():
        print(f"  {key:<35}: {value}")

    if strategy["status"] == "paper_ready":
        print()
        print("[OK] paper-only historical-bar strategy score generated")
        return True
    print()
    print("[WARN] paper-only historical-bar strategy is not ready")
    return False
